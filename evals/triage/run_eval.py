#!/usr/bin/env python3
"""Run the triage eval: 21 synthetic cases, triage via the Claude Code CLI.

For each (case, rep) the runner builds the reference and comparison fit
tables, runs the real comparison (stdiag.compare_runs) and the real triage
(stdiag.triage_agent --backend claude-code) in a fresh work directory, and
grades findings_*.json with grade.py (code only). Results go to
evals/triage/runs/<variant>/:
  results.jsonl           one row per scored (case, rep), written as it
                          completes; reruns skip rows already present
  traces/<id>_rep<k>.json system prompt, user message, triage answer
  errors.jsonl            attempts that produced nothing scorable
                          (CLI failure, timeout, wrong model served)
  work/<id>_rep<k>/       the run's input and output files

Before the first run, and after any change to the files it uses, the
reviewer approves the harness:  python evals/triage/run_eval.py --approve-harness
(this records a checksum and runs nothing). --self-test grades perfect,
empty, missing and merged answers on every case without calling any AI.

Usage:
  python evals/triage/run_eval.py --self-test
  python evals/triage/run_eval.py --cases null-1,stave-mvtx-rphi,mixed-1 --reps 1
  python evals/triage/run_eval.py --reps 2
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from evals.triage.cases import CASES, LABELS  # noqa: E402
from evals.triage.grade import grade, injection_rows, KEY, key_of  # noqa: E402
from stdiag import triage_agent  # noqa: E402
from synthetic.make_synthetic_fit_tables import build_tables  # noqa: E402

FLOW_DIR = REPO_ROOT / "evals" / "triage" / "runs"
HARNESS_PATHS = ["evals/triage/run_eval.py", "evals/triage/cases.py",
                 "evals/triage/grade.py", "stdiag/triage_agent.py",
                 "stdiag/compare_runs.py",
                 "synthetic/make_synthetic_fit_tables.py"]
METRICS = [
    {"id": "pass", "label": "Pass", "kind": "binary"},
    {"id": "recall", "label": "Recall", "kind": "float", "scale": 1},
    {"id": "group_acc", "label": "Group acc.", "kind": "float", "scale": 1},
    {"id": "false_findings", "label": "False finds", "kind": "float",
     "scale": 5, "better": "lower"},
    {"id": "merged", "label": "Merged", "kind": "float", "scale": 5,
     "better": "lower"},
    {"id": "validation", "label": "Validation", "kind": "binary"},
]
PERF_FIELDS = [
    {"id": "latency_s", "label": "Latency", "unit": "s"},
    {"id": "in_tokens", "label": "In tokens"},
    {"id": "out_tokens", "label": "Out tokens"},
    {"id": "reported_cost_usd", "label": "Cost (CC)", "unit": "$"},
]
MAX_ATTEMPTS = 2
WRITE_LOCK = threading.Lock()


def harness_sha() -> str:
    digest = hashlib.sha256()
    for path in HARNESS_PATHS:
        digest.update(path.encode() + b"\0" + (REPO_ROOT / path).read_bytes())
    return digest.hexdigest()


def python_module(module: str, *args: str, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", module, *args], cwd=REPO_ROOT, text=True,
        capture_output=True, timeout=timeout,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT),
             "PYTHONDONTWRITEBYTECODE": "1"})


def describe(case: dict) -> str:
    parts = []
    for injection in case["injections"]:
        changes = [f"{key}={injection[key]}" for key in
                   ("offset_mm", "sigma_scale", "entries", "missing")
                   if key in injection]
        where = (f"{injection['detector']} L{injection['layer']} staves "
                 f"{injection['staves'] or 'all'} chips "
                 f"{injection['chips'] or 'all'} {injection['coord'] or 'both'}")
        parts.append(f"{injection['name']} ({where}; {', '.join(changes)}; "
                     f"expected {injection['expected']})")
    return f"{case['id']}: " + ("; ".join(parts) or "no injected change")


def build_inputs(case: dict, work: Path) -> tuple[Path, Path]:
    """Fit tables and comparison outputs for one case (no AI)."""
    work.mkdir(parents=True, exist_ok=True)
    for label, table in build_tables(case["seed"], case["injections"],
                                     LABELS).items():
        table.to_csv(work / f"residual_fits_{label}.csv", index=False,
                     float_format="%.8g")
    result = python_module("stdiag.compare_runs",
                           str(work / "residual_fits_Ref.csv"),
                           str(work / "residual_fits_Cmp.csv"),
                           "--out-dir", str(work), timeout=300)
    if result.returncode:
        raise RuntimeError(f"compare_runs failed: {result.stderr[-500:]}")
    return work / "flags_Ref_vs_Cmp.csv", work / "summary_Ref_vs_Cmp.json"


def trace_turns(flags: Path, summary: Path, answer: str) -> list[dict]:
    dry = python_module("stdiag.triage_agent", str(flags), str(summary),
                        "--backend", "claude-code", "--dry-run", timeout=300)
    text = dry.stdout
    system = text.split("=== System prompt ===\n", 1)[-1].split(
        "=== User message (complete) ===\n", 1)
    user = system[1].rsplit("\nDry run only; nothing was sent.", 1)[0] \
        if len(system) > 1 else ""
    return [{"role": "system", "content": system[0].strip()},
            {"role": "user", "content": user.strip()},
            {"role": "assistant", "content": answer}]


def append_jsonl(path: Path, row: dict) -> None:
    with WRITE_LOCK, path.open("a") as handle:
        handle.write(json.dumps(row) + "\n")


def done_keys(results: Path) -> set[tuple[str, int]]:
    if not results.exists():
        return set()
    return {(row["prompt_id"], row["rep"]) for row in
            map(json.loads, results.read_text().splitlines()) if row}


def run_one(case: dict, rep: int, variant_dir: Path, model: str,
            timeout_s: float) -> str:
    work = variant_dir / "work" / f"{case['id']}_rep{rep}"
    flags_path, summary_path = build_inputs(case, work)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        for stale in work.glob("findings_*.json"):
            stale.unlink()
        usage_path = work / "triage_usage.json"
        usage_path.unlink(missing_ok=True)
        start = time.monotonic()
        failure, detail = None, ""
        try:
            result = python_module(
                "stdiag.triage_agent", str(flags_path), str(summary_path),
                "--backend", "claude-code", "--model", model,
                "--usage-out", str(usage_path), timeout=timeout_s)
            if result.returncode:
                failure, detail = "cli_error", result.stderr[-1000:]
        except subprocess.TimeoutExpired:
            failure, detail = "timeout", f"> {timeout_s} s"
        wall_s = time.monotonic() - start
        usage = (json.loads(usage_path.read_text())
                 if usage_path.exists() else {})
        if not failure and model not in (usage.get("models") or [model]):
            failure = "model_mismatch"
            detail = f"served {usage.get('models')}, requested {model}"
        if failure:
            append_jsonl(variant_dir / "errors.jsonl", {
                "prompt_id": case["id"], "rep": rep, "attempt": attempt,
                "failure_class": failure, "detail": detail,
                "model": ",".join(usage.get("models", [])),
                "usage": usage.get("usage", {}), "wall_s": round(wall_s, 1)})
            if attempt < MAX_ATTEMPTS:
                time.sleep(random.uniform(10, 30))
            continue

        findings = json.loads((work / "findings_Ref_vs_Cmp.json").read_text())
        flags = pd.read_csv(flags_path, dtype={"detector": str, "coord": str})
        graded = grade(case, flags, findings)
        report = (work / "triage_report_Ref_vs_Cmp.md").read_text()
        trace_dir = variant_dir / "traces"
        trace_dir.mkdir(exist_ok=True)
        (trace_dir / f"{case['id']}_rep{rep}.json").write_text(json.dumps(
            trace_turns(flags_path, summary_path, report
                        + "\n\n```json\n" + json.dumps(findings, indent=2)
                        + "\n```"), indent=1))
        token_usage = usage.get("usage", {})
        append_jsonl(variant_dir / "results.jsonl", {
            "prompt_id": case["id"], "rep": rep, "prompt": describe(case),
            "tags": [case["tag"]], "status": "ok",
            "stop_reason": usage.get("subtype", ""),
            "grade": graded["grade"], "meta": graded["meta"]
            | {"attempt": attempt, "num_turns": usage.get("num_turns")},
            "model": model, "usage": token_usage,
            "latency_s": round(usage.get("duration_ms", wall_s * 1000) / 1000, 1),
            "in_tokens": token_usage.get("input_tokens", 0)
            + token_usage.get("cache_read_input_tokens", 0)
            + token_usage.get("cache_creation_input_tokens", 0),
            "out_tokens": token_usage.get("output_tokens", 0),
            "reported_cost_usd": usage.get("total_cost_usd"),
            "wall_s": round(wall_s, 1)})
        verdict = "PASS" if graded["grade"]["pass"] else "fail"
        return f"{case['id']} rep{rep}: {verdict} {graded['grade']}"
    return f"{case['id']} rep{rep}: ERROR (see errors.jsonl)"


def oracle_findings(case: dict, flags: pd.DataFrame) -> dict:
    flagged = {key_of(row) for row in
               flags.loc[flags["flagged"], KEY].itertuples(index=False)}
    findings, assigned = [], set()
    for injection in case["injections"]:
        rows = injection_rows(injection, flagged) - assigned
        if rows:
            group = injection["expected"] if injection["expected"] in (
                "A", "B", "C", "D") else "E"
            findings.append({"group": group, "entries": sorted(rows)})
            assigned |= rows
    if flagged - assigned:
        findings.append({"group": "E", "entries": sorted(flagged - assigned)})
    return {"findings": findings}


def as_findings(raw: dict) -> dict:
    """Give ids and entry dicts, then validate like triage_agent does."""
    findings = [{"id": f"F{index + 1}", "group": item["group"],
                 "title": "", "priority": index + 1,
                 "entries": [dict(zip(KEY, row)) for row in item["entries"]]}
                for index, item in enumerate(raw["findings"])]
    return {"findings": findings,
            "validation": triage_agent.validate_findings({"findings": findings})}


def self_test(cases: list[dict], work_root: Path) -> int:
    """Oracle must pass everywhere; null/no-JSON/merge-all must not."""
    failures = 0
    for case in cases:
        flags_path, _ = build_inputs(case, work_root / case["id"])
        flags = pd.read_csv(flags_path, dtype={"detector": str, "coord": str})
        triage_agent.ComparisonData.flags = flags
        oracle = oracle_findings(case, flags)
        all_flagged = sorted({key_of(row) for row in flags.loc[
            flags["flagged"], KEY].itertuples(index=False)})
        answers = {
            "oracle": as_findings(oracle),
            "empty": as_findings({"findings": []}),
            "no_json": {"findings": [], "validation": {"passed": False}},
            "merge_all": as_findings({"findings": [
                {"group": "A", "entries": all_flagged}] if all_flagged else []}),
        }
        scores = {name: grade(case, flags, answer)
                  for name, answer in answers.items()}
        required = scores["oracle"]["meta"]["required_injections"]
        expected = {"oracle": True, "no_json": False,
                    "empty": not all_flagged}
        if required > 1:
            expected["merge_all"] = False
        problems = [name for name, want in expected.items()
                    if bool(scores[name]["grade"]["pass"]) != want]
        failures += bool(problems)
        print(f"{case['id']:<20} flagged={len(all_flagged):>3} "
              f"required={required} "
              + " ".join(f"{name}={int(score['grade']['pass'])}"
                         for name, score in scores.items())
              + (f"  UNEXPECTED: {problems}" if problems else ""))
    print("self-test", "FAILED" if failures else "passed",
          f"({failures} case(s) with unexpected grades)")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", help="comma-separated case ids (default all)")
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--variant", default="baseline")
    parser.add_argument("--model", default=triage_agent.DEFAULT_MODEL)
    parser.add_argument("--timeout-s", type=float, default=1200)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--approve-harness", action="store_true",
                        help="record the harness checksum (reviewer only)")
    args = parser.parse_args()

    cases = CASES
    if args.cases:
        wanted = args.cases.split(",")
        unknown = set(wanted) - {case["id"] for case in CASES}
        if unknown:
            sys.exit(f"unknown case ids: {sorted(unknown)}")
        cases = [case for case in CASES if case["id"] in wanted]

    FLOW_DIR.mkdir(parents=True, exist_ok=True)
    if args.self_test:
        sys.exit(self_test(cases, FLOW_DIR / "self_test"))

    approval = FLOW_DIR / "_harness_approval.json"
    if args.approve_harness:
        approval.write_text(json.dumps({"sha256": harness_sha(),
                                        "paths": HARNESS_PATHS}, indent=2))
        print(f"Harness approved: {harness_sha()[:12]}")
        return
    if not approval.exists() or json.loads(
            approval.read_text())["sha256"] != harness_sha():
        print("The harness is not approved or has changed since approval. "
              "The reviewer must run:\n  python evals/triage/run_eval.py "
              "--approve-harness", file=sys.stderr)
        sys.exit(2)

    (FLOW_DIR / "_state.json").write_text(json.dumps({
        "metrics": METRICS, "perf_fields": PERF_FIELDS,
        "harness_paths": HARNESS_PATHS}, indent=2))
    variant_dir = FLOW_DIR / args.variant
    variant_dir.mkdir(exist_ok=True)
    done = done_keys(variant_dir / "results.jsonl")
    todo = [(case, rep) for case in cases for rep in range(args.reps)
            if (case["id"], rep) not in done]
    print(f"{len(todo)} run(s) to do ({len(done)} already done), "
          f"model {args.model}, concurrency {args.concurrency}")
    with concurrent.futures.ThreadPoolExecutor(args.concurrency) as pool:
        futures = [pool.submit(run_one, case, rep, variant_dir, args.model,
                               args.timeout_s) for case, rep in todo]
        for future in concurrent.futures.as_completed(futures):
            print(future.result(), flush=True)


if __name__ == "__main__":
    main()
