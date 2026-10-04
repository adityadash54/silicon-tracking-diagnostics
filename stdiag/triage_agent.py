#!/usr/bin/env python3
"""Layer 3: AI triage of the flags produced by compare_runs.py.

Reads only layer-2 outputs (flags_<A>_vs_<B>.csv and summary_<A>_vs_<B>.json)
and asks Claude to group and interpret the flagged chips. The deterministic
flags are never changed; Claude only interprets them.

Backends:
  --backend api (default): Anthropic Python SDK tool runner. Claude calls the
      read-only tools below. Sends the summary JSON (labels, list-file names,
      thresholds, counts) and the per-chip fit-summary rows Claude requests.
      Credentials: ANTHROPIC_API_KEY, or a profile from `ant auth login`.
  --backend claude-code: runs the Claude Code CLI (`claude -p`) on the
      user's Claude Code login; no API key needed. The CLI cannot call Python
      tools, so their outputs (summary, flagged rows, per-stave overview of
      every layer with a flag, every row of each flagged stave,
      not-comparable rows, notable unflagged rows) are computed locally and
      sent in one prompt. It runs with no tools and no MCP connectors from an
      empty temporary directory, so it cannot read project files; other
      user-level ~/.claude settings may still load. --effort and
      --no-fallback are ignored.
No ROOT files, hits or tracks are read or sent by either backend. Use
--dry-run to print what would be sent without contacting anything.

Usage:
  python -m stdiag.triage_agent flags_Iter0_vs_Iter1.csv summary_Iter0_vs_Iter1.json
  python -m stdiag.triage_agent flags_Iter0_vs_Iter1.csv summary_Iter0_vs_Iter1.json --dry-run
  python -m stdiag.triage_agent flags_Iter0_vs_Iter1.csv summary_Iter0_vs_Iter1.json \
      --backend claude-code
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import inspect
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_MODEL = "claude-opus-5-5"
ROW_COLUMNS = [
    "detector", "layer", "stave", "chip", "coord", "comparison_status",
    "flag_mean", "flag_width", "delta_mu_mm", "mu_z", "separation",
    "min_shift_mm", "sigma_1_mm", "sigma_2_mm", "sigma_rel",
    "sigma_rel_significance", "entries_1", "entries_2", "fit_status_1",
    "fit_status_2", "reason",
]

SYSTEM_PROMPT = """\
You are assisting an sPHENIX silicon-tracking expert who is checking MVTX and \
INTT alignment and detector stability. A deterministic program has fitted a \
Gaussian to the local residual distribution of every MVTX chip (9 per stave, \
layers 0-2) and INTT sensor (4 per ladder, layers 3-6), in local r-phi and \
local z, for a reference input and a comparison input, and has flagged \
entries using fixed criteria that you can read with get_comparison_summary.

The flags are final. Never recompute, add or remove flags. Your job is to \
interpret them using the tools, which read the comparison tables.

Group the flagged entries into:
A. Coherent stave/ladder-wide mean shifts (most chips of one stave shift in \
the same direction): likely stave-level misalignment.
B. Isolated chip/sensor mean shifts: likely chip-level misalignment, or a \
local hardware/calibration change.
C. Width-only changes: check sigma_rel_significance; values below ~2 are \
compatible with statistical fluctuation.
D. Mean and width changes together.
E. Entries near the statistics limit or with suspicious fits.
Also report patterns across layers, staves, coordinates and the \
not-comparable entries (for example a whole stave missing in one input). \
Use list_notable_unflagged for entries that are noteworthy but not flagged \
(significant shifts below the minimum shift, highly significant small width \
changes, low statistics); mention them, but they stay unflagged.

Rules:
- Base every statement on tool output. Quote layer, stave, chip, coordinate \
and numbers. Report shifts and widths in micrometres for MVTX and INTT r-phi, \
and in millimetres for INTT z.
- INTT z residuals are not Gaussian, so treat INTT z fits as indicative only.
- Refer to the inputs only by their labels. You do not know the detector \
configuration behind a label; never guess it. The user records \
configurations by hand.
- State uncertainty plainly. Do not recommend changes to detector operation; \
recommend checks.

Finish with a Markdown report (no top-level title) with these sections:
### Overview
### Grouped findings  (a table: group, entries, evidence)
### Inspect first  (prioritised list of staves/chips with the reason)
### Likely statistical or benign
### Suggested follow-up checks

After the report, end with one fenced ```json block and nothing after it:
{"findings": [{"id": "F1", "group": "A", "title": "...", "priority": 1,
  "entries": [{"detector": "MVTX", "layer": 1, "stave": 4, "chip": 0,
  "coord": "rphi"}], "evidence": "one line with the key numbers"}]}
Number the ids F1, F2, ... in priority order. Every flagged entry must \
appear in exactly one finding. Not-comparable or notable-unflagged entries \
may form findings of their own.
"""


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class ComparisonData:
    """Holds the layer-2 tables that the tools read."""

    flags = pd.DataFrame()
    summary: dict = {}


def to_json(payload) -> str:
    return json.dumps(payload, default=str)


def frame_rows(frame: pd.DataFrame, limit: int) -> str:
    limited = frame.head(max(limit, 0))
    rows = json.loads(limited[ROW_COLUMNS].to_json(
        orient="records", double_precision=6))
    return to_json({"total_matching": int(len(frame)),
                    "returned": len(rows), "rows": rows})


def filter_rows(detector: str = "", layer: int = -1,
                coord: str = "") -> pd.DataFrame:
    flags = ComparisonData.flags
    mask = pd.Series(True, index=flags.index)
    if detector:
        mask &= flags["detector"].str.upper() == detector.upper()
    if layer >= 0:
        mask &= flags["layer"] == layer
    if coord:
        mask &= flags["coord"] == coord
    return flags.loc[mask]


def get_comparison_summary() -> str:
    """Return the comparison summary: input labels and list files, flagging
    criteria and thresholds, and flag counts per detector, layer and
    coordinate."""
    return to_json(ComparisonData.summary)


def list_flagged_chips(detector: str = "", layer: int = -1, coord: str = "",
                       limit: int = 200) -> str:
    """List flagged entries with their fit comparison metrics.

    Args:
        detector: "MVTX" or "INTT"; empty for both.
        layer: Layer number 0-6; -1 for all layers.
        coord: "rphi" or "z"; empty for both.
        limit: Maximum number of rows to return.
    """
    frame = filter_rows(detector, layer, coord)
    return frame_rows(frame.loc[frame["flagged"]], limit)


def get_stave_overview(detector: str = "", coord: str = "",
                       only_with_flags: bool = True, layer: int = -1) -> str:
    """Summarise each stave/ladder: comparable and flagged chip counts and the
    spread of mean shifts, to separate stave-wide shifts from single chips.

    Args:
        detector: "MVTX" or "INTT"; empty for both.
        coord: "rphi" or "z"; empty for both.
        only_with_flags: If true, return only staves with at least one flag.
        layer: Layer number 0-6; -1 for all layers.
    """
    frame = filter_rows(detector, layer, coord)
    comparable = frame.loc[frame["comparable"]]
    shifts = comparable.groupby(["detector", "layer", "stave", "coord"])[
        "delta_mu_mm"]
    overview = pd.DataFrame({
        "chips": frame.groupby(["detector", "layer", "stave", "coord"]).size(),
        "comparable": comparable.groupby(
            ["detector", "layer", "stave", "coord"]).size(),
        "flagged": frame.groupby(["detector", "layer", "stave", "coord"])[
            "flagged"].sum(),
        "flag_mean": frame.groupby(["detector", "layer", "stave", "coord"])[
            "flag_mean"].sum(),
        "flag_width": frame.groupby(["detector", "layer", "stave", "coord"])[
            "flag_width"].sum(),
        "median_delta_mu_mm": shifts.median(),
        "std_delta_mu_mm": shifts.std(),
        "fraction_positive_shift": shifts.apply(
            lambda values: float(np.mean(values > 0))),
    }).fillna({"comparable": 0}).reset_index()
    if only_with_flags:
        overview = overview.loc[overview["flagged"] > 0]
    overview = overview.sort_values(["flagged", "detector", "layer", "stave"],
                                    ascending=[False, True, True, True])
    return to_json(json.loads(overview.to_json(orient="records",
                                               double_precision=6)))


def get_stave_rows(layer: int, stave: int) -> str:
    """Return every chip/sensor row (both coordinates) of one stave/ladder.

    Args:
        layer: Layer number 0-6.
        stave: Stave (MVTX) or ladder (INTT) number.
    """
    flags = ComparisonData.flags
    frame = flags.loc[(flags["layer"] == layer) & (flags["stave"] == stave)]
    return frame_rows(frame, 100)


def list_not_comparable(detector: str = "", limit: int = 200) -> str:
    """List entries that could not be compared (missing, low statistics or
    failed fit in either input).

    Args:
        detector: "MVTX" or "INTT"; empty for both.
        limit: Maximum number of rows to return.
    """
    frame = filter_rows(detector)
    return frame_rows(frame.loc[~frame["comparable"]], limit)


NOTABLE_MU_Z = 5.0
NOTABLE_WIDTH_SIGNIFICANCE = 4.0
NOTABLE_LOW_ENTRIES = 200


def list_notable_unflagged(detector: str = "", limit: int = 200) -> str:
    """List comparable entries that are not flagged but worth knowing about:
    mean shift with z > 5 (significant but below the minimum shift), width
    change with significance > 4, or fewer than 200 entries in either input.
    The reason column says which.

    Args:
        detector: "MVTX" or "INTT"; empty for both.
        limit: Maximum number of rows to return.
    """
    frame = filter_rows(detector)
    frame = frame.loc[frame["comparable"] & ~frame["flagged"]]
    significant_shift = frame["mu_z"] > NOTABLE_MU_Z
    significant_width = (frame["sigma_rel_significance"]
                         > NOTABLE_WIDTH_SIGNIFICANCE)
    low_entries = (frame[["entries_1", "entries_2"]].min(axis=1)
                   < NOTABLE_LOW_ENTRIES)
    notes = pd.DataFrame({
        f"significant shift below minimum (z > {NOTABLE_MU_Z:g})":
            significant_shift,
        f"width change significance > {NOTABLE_WIDTH_SIGNIFICANCE:g}":
            significant_width,
        f"low statistics (N < {NOTABLE_LOW_ENTRIES})": low_entries,
    })
    notable = notes.any(axis=1)
    reasons = notes.loc[notable].apply(
        lambda row: "; ".join(row.index[row]), axis=1)
    return frame_rows(frame.loc[notable].assign(reason=reasons), limit)


TOOL_FUNCTIONS = [get_comparison_summary, list_flagged_chips,
                  get_stave_overview, get_stave_rows, list_not_comparable,
                  list_notable_unflagged]


def user_message(summary: dict) -> str:
    reference = summary["inputs"]["reference"]["label"]
    comparison = summary["inputs"]["comparison"]["label"]
    return (f"Triage the comparison of '{comparison}' against the reference "
            f"'{reference}'. Start with get_comparison_summary, then "
            "investigate the flagged entries and write the report.")


def print_dry_run(summary: dict) -> None:
    print("=== System prompt ===\n" + SYSTEM_PROMPT)
    print("=== First user message ===\n" + user_message(summary) + "\n")
    print("=== Tools (Claude chooses which to call; outputs come from the "
          "local tables) ===")
    for function in TOOL_FUNCTIONS:
        print(f"- {function.__name__}{inspect.signature(function)}: "
              f"{inspect.getdoc(function).splitlines()[0]}")
    print("\n=== Sample tool output: get_comparison_summary() ===")
    print(get_comparison_summary())
    print("\n=== Sample tool output: list_flagged_chips(limit=5) ===")
    print(list_flagged_chips(limit=5))
    print("\nDry run only; nothing was sent.")


def run_triage(summary: dict, model: str, effort: str,
               use_fallback: bool) -> tuple[str, str]:
    import anthropic
    from anthropic import beta_tool

    request = {
        "model": model,
        "max_tokens": 16000,
        "system": SYSTEM_PROMPT,
        "tools": [beta_tool(function) for function in TOOL_FUNCTIONS],
        "messages": [{"role": "user", "content": user_message(summary)}],
        "output_config": {"effort": effort},
    }
    if use_fallback:
        # Server-side fallback reruns a safety-declined request on
        # Anthropic's recommended fallback model.
        request["betas"] = ["server-side-fallback-2026-07-01"]
        request["extra_body"] = {"fallbacks": "default"}

    client = anthropic.Anthropic()
    final_message = None
    try:
        for message in client.beta.messages.tool_runner(**request):
            final_message = message
            for block in message.content:
                if block.type == "tool_use":
                    print(f"  tool call: {block.name}"
                          f"({json.dumps(block.input)})", file=sys.stderr)
    except anthropic.AuthenticationError:
        sys.exit("ERROR: authentication failed. Set ANTHROPIC_API_KEY or run "
                 "`ant auth login`.")
    except anthropic.BadRequestError as error:
        sys.exit(f"ERROR: request rejected: {error.message} "
                 "(if it mentions fallbacks, retry with --no-fallback)")
    except anthropic.RateLimitError:
        sys.exit("ERROR: rate limited; retry later.")
    except anthropic.APIStatusError as error:
        sys.exit(f"ERROR: API error {error.status_code}: {error.message}")
    except anthropic.APIConnectionError:
        sys.exit("ERROR: could not reach the Anthropic API.")

    if final_message is None:
        sys.exit("ERROR: no response received.")
    if final_message.stop_reason == "refusal":
        sys.exit("ERROR: the request was declined; no report written.")
    if final_message.stop_reason == "max_tokens":
        print("WARNING: response hit max_tokens; the report may be "
              "truncated.", file=sys.stderr)

    text = "\n".join(block.text for block in final_message.content
                     if block.type == "text").strip()
    return text, final_message.model


OFFLINE_NOTE = """
In this run you have no tools. The outputs of the tools named above
(get_comparison_summary, list_flagged_chips, get_stave_overview for every
stave of each layer that has a flag, get_stave_rows for every stave with a
flag, list_not_comparable, list_notable_unflagged) are given in the user
message; use only that data.
"""


def build_offline_context(summary: dict) -> str:
    flags = ComparisonData.flags
    flagged_staves = (flags.loc[flags["flagged"], ["layer", "stave"]]
                      .drop_duplicates().sort_values(["layer", "stave"]))
    blocks = [
        user_message(summary).replace(
            "Start with get_comparison_summary, then investigate",
            "Use the tool outputs below to investigate"),
        "## get_comparison_summary()\n" + get_comparison_summary(),
        "## list_flagged_chips(limit=2000)\n" + list_flagged_chips(limit=2000),
    ]
    blocks += [f"## get_stave_overview(only_with_flags=False, layer={layer})\n"
               + get_stave_overview(only_with_flags=False, layer=int(layer))
               for layer in sorted(flagged_staves["layer"].unique())]
    blocks += [f"## get_stave_rows(layer={layer}, stave={stave})\n"
               + get_stave_rows(int(layer), int(stave))
               for layer, stave in flagged_staves.itertuples(index=False)]
    blocks.append("## list_not_comparable(limit=2000)\n"
                  + list_not_comparable(limit=2000))
    blocks.append("## list_notable_unflagged(limit=2000)\n"
                  + list_notable_unflagged(limit=2000))
    return "\n\n".join(blocks)


def run_triage_claude_code(summary: dict,
                           model: str) -> tuple[str, str, dict]:
    claude = shutil.which("claude")
    if claude is None:
        sys.exit("ERROR: the Claude Code CLI 'claude' was not found on PATH.")

    command = [claude, "-p", "--output-format", "json", "--model", model,
               "--tools", "", "--strict-mcp-config", "--no-session-persistence",
               "--system-prompt", SYSTEM_PROMPT + OFFLINE_NOTE]
    # An empty working directory keeps project files (and any synthetic
    # truth) out of the CLI's context.
    with tempfile.TemporaryDirectory() as empty_directory:
        try:
            result = subprocess.run(
                command, input=build_offline_context(summary), text=True,
                capture_output=True, timeout=1800, cwd=empty_directory)
        except subprocess.TimeoutExpired:
            sys.exit("ERROR: the Claude Code CLI did not finish in 30 minutes.")

    try:
        reply = json.loads(result.stdout)
    except json.JSONDecodeError:
        reply = {"result": result.stdout}
    text = str(reply.get("result", "")).strip()
    if result.returncode != 0 or reply.get("is_error") or not text:
        sys.exit(f"ERROR: the Claude Code CLI failed (exit {result.returncode})"
                 f": {result.stderr.strip() or 'no output'}")
    usage = {"models": sorted(reply.get("modelUsage", {})),
             "usage": reply.get("usage", {}),
             "total_cost_usd": reply.get("total_cost_usd"),
             "duration_ms": reply.get("duration_ms"),
             "num_turns": reply.get("num_turns"),
             "subtype": reply.get("subtype")}
    return text, f"{model} via Claude Code CLI", usage


FINDINGS_BLOCK = re.compile(r"```json\s*(\{.*\})\s*```\s*$", re.DOTALL)
ENTRY_KEYS = ["detector", "layer", "stave", "chip", "coord"]


def split_findings(triage_text: str) -> tuple[str, dict | None]:
    match = FINDINGS_BLOCK.search(triage_text)
    if not match:
        return triage_text, None
    try:
        findings = json.loads(match.group(1))
    except json.JSONDecodeError:
        return triage_text, None
    return triage_text[:match.start()].rstrip(), findings


def entry_key(values) -> tuple:
    return tuple(str(value) for value in values)


def validate_findings(findings: dict | None) -> dict:
    if not findings or not isinstance(findings.get("findings"), list):
        return {"passed": False,
                "problem": "no findings JSON block in the response"}

    flags = ComparisonData.flags
    known = {entry_key(row)
             for row in flags[ENTRY_KEYS].itertuples(index=False)}
    flagged = {entry_key(row) for row in
               flags.loc[flags["flagged"], ENTRY_KEYS].itertuples(index=False)}
    assigned: dict[tuple, list[str]] = {}
    unknown = []
    for finding in findings["findings"]:
        for entry in finding.get("entries", []):
            key = entry_key(entry.get(column) for column in ENTRY_KEYS)
            if key not in known:
                unknown.append(list(key))
            assigned.setdefault(key, []).append(str(finding.get("id")))

    unassigned = sorted(flagged - assigned.keys())
    duplicated = {" ".join(key): ids for key, ids in assigned.items()
                  if key in flagged and len(ids) > 1}
    return {"passed": not unassigned and not unknown,
            "unassigned_flagged": [list(key) for key in unassigned],
            "unknown_entries": unknown,
            "flagged_in_several_findings": duplicated}


def validation_line(findings_name: str, validation: dict) -> str:
    if validation["passed"]:
        return f"Structured findings: {findings_name}, validation passed."
    if "problem" in validation:
        return (f"Structured findings: {findings_name}, validation FAILED: "
                f"{validation['problem']}.")
    return (f"Structured findings: {findings_name}, validation FAILED: "
            f"{len(validation['unassigned_flagged'])} flagged entries not in "
            f"any finding, {len(validation['unknown_entries'])} unknown "
            "entries.")


def build_report(summary: dict, flags_path: Path, summary_path: Path,
                 model: str, triage_text: str, validation_text: str) -> str:
    reference = summary["inputs"]["reference"]
    comparison = summary["inputs"]["comparison"]
    criteria = summary["criteria"]
    counts = summary["counts"]
    generated = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    min_shift = ", ".join(f"{key} {1000.0 * value:g} um"
                          for key, value in criteria["min_shift_mm"].items())
    return "\n\n".join([
        f"# AI triage: {comparison['label']} vs {reference['label']}",
        f"Generated {generated} by triage_agent.py with {model}. The "
        "interpretation below is AI-generated from the deterministic flags of "
        "compare_runs.py; verify it against the residual plots before acting.",
        "## Inputs and detector configuration",
        "Record the detector/reconstruction configuration of each label "
        "below.",
        "| Role | Label | List file | Detector configuration (fill in) |\n"
        "|---|---|---|---|\n"
        f"| reference | {reference['label']} | {reference['listfile']} | |\n"
        f"| comparison | {comparison['label']} | {comparison['listfile']} | |",
        f"Source: {flags_path.name} (sha256 {sha256sum(flags_path)[:12]}), "
        f"{summary_path.name} (sha256 {sha256sum(summary_path)[:12]}).",
        "## Criteria",
        f"- Width: |(sigma2 - sigma1)/sigma1| > "
        f"{criteria['sigma_rel_threshold']}\n"
        f"- Mean: |mu2 - mu1| / sqrt(dmu1^2 + dmu2^2) > "
        f"{criteria['z_threshold']} and |mu2 - mu1| > minimum shift "
        f"({min_shift})\n"
        "- Flagged if width OR mean fires.",
        f"Flagged {counts['flagged']} of {counts['comparable']} comparable "
        f"entries ({counts['flag_mean']} mean, {counts['flag_width']} width, "
        f"{counts['not_comparable']} not comparable).",
        validation_text,
        "## AI triage",
        triage_text,
    ]) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("flags", type=Path, help="flags_<A>_vs_<B>.csv")
    parser.add_argument("summary", type=Path, help="summary_<A>_vs_<B>.json")
    parser.add_argument("--out", type=Path,
                        help="report path (default triage_report_<A>_vs_<B>.md "
                             "next to the flags file)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="high",
                        choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--no-fallback", action="store_true",
                        help="disable the server-side refusal fallback")
    parser.add_argument("--backend", default="api",
                        choices=["api", "claude-code"],
                        help="api: Anthropic SDK (API key); claude-code: the "
                             "`claude -p` CLI on your Claude Code login")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be sent and exit")
    parser.add_argument("--usage-out", type=Path,
                        help="write the run's model, tokens, cost and time "
                             "as JSON (claude-code backend)")
    args = parser.parse_args()

    ComparisonData.flags = pd.read_csv(
        args.flags, dtype={"detector": str, "coord": str, "reason": str})
    ComparisonData.summary = json.loads(args.summary.read_text())

    if args.dry_run and args.backend == "claude-code":
        print("=== System prompt ===\n" + SYSTEM_PROMPT + OFFLINE_NOTE)
        print("=== User message (complete) ===\n"
              + build_offline_context(ComparisonData.summary))
        print("\nDry run only; nothing was sent.")
        return
    if args.dry_run:
        print_dry_run(ComparisonData.summary)
        return

    if args.backend == "claude-code":
        print("Note: --effort and --no-fallback do not apply to the "
              "claude-code backend.", file=sys.stderr)
        triage_text, served_model, usage = run_triage_claude_code(
            ComparisonData.summary, args.model)
    else:
        triage_text, served_model = run_triage(
            ComparisonData.summary, args.model, args.effort,
            not args.no_fallback)
        usage = {}
    stem = args.flags.stem.removeprefix("flags_")
    out_path = args.out or args.flags.with_name(f"triage_report_{stem}.md")
    report_text, findings = split_findings(triage_text)
    validation = validate_findings(findings)
    findings_path = args.flags.with_name(f"findings_{stem}.json")
    inputs = ComparisonData.summary["inputs"]
    findings_path.write_text(json.dumps({
        "reference": {key: inputs["reference"][key]
                      for key in ("label", "listfile")},
        "comparison": {key: inputs["comparison"][key]
                       for key in ("label", "listfile")},
        "source": {"flags": args.flags.name, "summary": args.summary.name,
                   "report": out_path.name},
        "model": served_model,
        "validation": validation,
        "findings": (findings or {}).get("findings", []),
    }, indent=2) + "\n")
    out_path.write_text(build_report(
        ComparisonData.summary, args.flags, args.summary, served_model,
        report_text, validation_line(findings_path.name, validation)))
    print(f"Wrote {out_path} and {findings_path}")
    if args.usage_out:
        args.usage_out.write_text(json.dumps(usage, indent=2) + "\n")
    if not validation["passed"]:
        print(f"WARNING: {validation_line(findings_path.name, validation)}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
