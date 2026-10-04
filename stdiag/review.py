#!/usr/bin/env python3
"""Human review of triage findings, with optional coresoftware and tracking experts.

Reads findings_<A>_vs_<B>.json (written by triage_agent.py), lets a reviewer
list and inspect findings, ask the coresoftware expert (coresoftware_expert.py)
why a finding might have happened, optionally have the tracking expert
(tracking_expert.py, ACTS + Millepede-II) check that answer against the
documentation, and record a decision. Everything is logged to
review_<A>_vs_<B>.json (the state; a web page can read it later) and
review_<A>_vs_<B>.md (human-readable), next to the findings file.

Commands:
  python -m stdiag.review list   findings_Iter0_vs_Iter1.json
  python -m stdiag.review show   findings_Iter0_vs_Iter1.json F3
  python -m stdiag.review ask    findings_Iter0_vs_Iter1.json F3 [--since 2026-06-01]
                          [--from REV --to REV] [--labels labels.csv]
                          [--no-dialogue] [--dry-run]
  python -m stdiag.review continue findings_Iter0_vs_Iter1.json F3 [--note "..."]
  python -m stdiag.review check  findings_Iter0_vs_Iter1.json F3 [--answer FILE] [--dry-run]
  python -m stdiag.review decide findings_Iter0_vs_Iter1.json F3 accept|reject|needs-info
                          --note "..."

`ask` starts a dialogue (expert_dialogue.py): the coresoftware expert and
the tracking expert exchange up to 3 turns each per round. It stops when
they converge, when one needs information from you, or at the limit;
`continue` sends your note to both and, after the limit, allows another
round. `--no-dialogue` gives a single coresoftware expert answer instead.

Revision range for `ask`: --from/--to if given; otherwise the
coresoftware_commit of both labels in labels.csv; otherwise the --since
(and optional --until) date window. `check` reviews the latest answer or
dialogue transcript for the finding unless --answer is given. Only `ask`,
`continue` and `check` contact Anthropic, and only without --dry-run.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import getpass
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from stdiag import expert_dialogue
from stdiag.coresoftware_expert import DEFAULT_MODEL, DEFAULT_REPO, ask_expert
from stdiag.tracking_expert import check_answer

DIALOGUE_STATUS_TEXT = {
    "converged": "experts converged",
    "needs_human": "experts have a question for you",
    "paused_at_limit": "awaiting your approval for another round",
}

ENTRY_KEYS = ["detector", "layer", "stave", "chip", "coord"]
ROW_COLUMNS = ENTRY_KEYS + [
    "comparison_status", "flag_mean", "flag_width", "delta_mu_mm", "mu_z",
    "separation", "sigma_1_mm", "sigma_2_mm", "sigma_rel",
    "sigma_rel_significance", "entries_1", "entries_2", "fit_status_1",
    "fit_status_2", "reason",
]


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_findings(path: Path) -> dict:
    findings = json.loads(path.read_text())
    if "findings" not in findings:
        sys.exit(f"ERROR: {path} has no 'findings' list.")
    return findings


def find(findings: dict, finding_id: str) -> dict:
    for finding in findings["findings"]:
        if finding["id"].upper() == finding_id.upper():
            return finding
    sys.exit(f"ERROR: no finding {finding_id}; see `review.py list`.")


def new_output_base(findings_path: Path, kind: str, finding_id: str) -> Path:
    """Timestamped output name (no suffix) that no existing file uses."""
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{kind}_{stem_of(findings_path)}_{finding_id}_{timestamp}"
    candidate, counter = findings_path.with_name(base), 2
    # Labels may contain dots, so append suffixes instead of with_suffix().
    while any(candidate.with_name(candidate.name + suffix).exists()
              for suffix in (".md", ".json")):
        candidate = findings_path.with_name(f"{base}_{counter}")
        counter += 1
    return candidate


def stem_of(path: Path) -> str:
    return path.stem.removeprefix("findings_")


def log_paths(findings_path: Path) -> tuple[Path, Path]:
    stem = stem_of(findings_path)
    return (findings_path.with_name(f"review_{stem}.json"),
            findings_path.with_name(f"review_{stem}.md"))


def load_log(findings_path: Path) -> list[dict]:
    json_path, _ = log_paths(findings_path)
    return json.loads(json_path.read_text()) if json_path.exists() else []


def flagged_rows(findings_path: Path, findings: dict, finding: dict) -> list:
    flags_name = findings.get("source", {}).get("flags")
    flags_path = findings_path.with_name(flags_name) if flags_name else None
    if flags_path is None or not flags_path.exists():
        return []
    flags = pd.read_csv(flags_path, dtype={"detector": str, "coord": str})
    wanted = pd.DataFrame(finding["entries"])[ENTRY_KEYS]
    rows = flags.merge(wanted, on=ENTRY_KEYS, how="inner")
    return json.loads(rows[ROW_COLUMNS].to_json(orient="records",
                                                 double_precision=6))


def write_log(findings_path: Path, findings: dict, events: list[dict]) -> None:
    json_path, md_path = log_paths(findings_path)
    json_path.write_text(json.dumps(events, indent=2) + "\n")

    reference = findings["reference"]["label"]
    comparison = findings["comparison"]["label"]
    lines = [f"# Review: {comparison} vs {reference}",
             f"Findings: {findings_path.name}. Updated {now_utc()}."]
    for finding in findings["findings"]:
        history = [event for event in events
                   if event["finding"] == finding["id"]]
        lines.append(f"## {finding['id']} ({finding.get('group', '?')}): "
                     f"{finding.get('title', '')}")
        if not history:
            lines.append("Not reviewed yet.")
        for event in history:
            if event["type"] == "ask":
                lines.append(f"- {event['time']} {event['reviewer']} asked the "
                             f"coresoftware expert ({event['revision']}): "
                             f"[{event['answer_file']}]({event['answer_file']})")
            elif event["type"] == "check":
                lines.append(f"- {event['time']} {event['reviewer']} had the "
                             f"tracking expert check {event['answer_file']}: "
                             f"[{event['check_file']}]({event['check_file']})")
            elif event["type"] == "dialogue":
                question = event.get("question_for_human", "")
                lines.append(
                    f"- {event['time']} {event['reviewer']}: expert dialogue "
                    f"{'continued' if event.get('continued') else 'started'}, "
                    f"now round {event['round']}, "
                    f"{DIALOGUE_STATUS_TEXT.get(event['status'], event['status'])}"
                    f": [{event['transcript_file']}]"
                    f"({event['transcript_file']})"
                    + (f". Question: {question}" if question else ""))
            else:
                lines.append(f"- {event['time']} {event['reviewer']}: "
                             f"**{event['decision']}**. {event.get('note', '')}")
    md_path.write_text("\n\n".join(lines) + "\n")


def append_event(findings_path: Path, findings: dict, event: dict) -> None:
    events = load_log(findings_path)
    events.append(event)
    write_log(findings_path, findings, events)


def read_labels(labels_path: Path, wanted: list[str]) -> dict:
    if not labels_path.exists():
        return {label: {} for label in wanted}
    with labels_path.open(newline="") as handle:
        rows = {row["label"]: row for row in csv.DictReader(handle)}
    return {label: rows.get(label, {}) for label in wanted}


def verify_revision(repo: Path, revision: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"],
        cwd=repo, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"ERROR: '{revision}' is not a commit in {repo}.")
    return result.stdout.strip()[:12]


def resolve_revision(args, labels: dict, reference: str,
                     comparison: str) -> dict:
    if args.from_rev and args.to_rev:
        return {"from": verify_revision(args.repo, args.from_rev),
                "to": verify_revision(args.repo, args.to_rev)}
    from_commit = labels[reference].get("coresoftware_commit", "").strip()
    to_commit = labels[comparison].get("coresoftware_commit", "").strip()
    if from_commit and to_commit:
        return {"from": verify_revision(args.repo, from_commit),
                "to": verify_revision(args.repo, to_commit),
                "source": "labels.csv"}
    if args.since:
        return {"since": args.since, "until": args.until or "now"}
    sys.exit(f"ERROR: labels.csv has no coresoftware_commit for both "
             f"'{reference}' and '{comparison}'; pass --since DATE or "
             "--from/--to.")


def command_list(args) -> None:
    findings = load_findings(args.findings)
    events = load_log(args.findings)
    validation = findings.get("validation", {})
    print(f"{findings['comparison']['label']} vs "
          f"{findings['reference']['label']}: {len(findings['findings'])} "
          f"findings; validation "
          f"{'passed' if validation.get('passed') else 'FAILED or missing'}")
    for finding in sorted(findings["findings"],
                          key=lambda item: item.get("priority", 99)):
        decisions = [event["decision"] for event in events
                     if event["finding"] == finding["id"]
                     and event["type"] == "decision"]
        asked = any(event["finding"] == finding["id"]
                    and event["type"] == "ask" for event in events)
        checked = any(event["finding"] == finding["id"]
                      and event["type"] == "check" for event in events)
        dialogues = [event for event in events
                     if event["finding"] == finding["id"]
                     and event["type"] == "dialogue"]
        dialogue = (", " + DIALOGUE_STATUS_TEXT.get(
            dialogues[-1]["status"], dialogues[-1]["status"])
            if dialogues else "")
        status = decisions[-1] if decisions else "open"
        print(f"  {finding['id']:>4}  group {finding.get('group', '?')}  "
              f"priority {finding.get('priority', '-')}  "
              f"{len(finding['entries']):>3} entries  [{status}"
              f"{', expert asked' if asked else ''}"
              f"{', checked' if checked else ''}{dialogue}]  "
              f"{finding.get('title', '')}")


def command_show(args) -> None:
    findings = load_findings(args.findings)
    finding = find(findings, args.finding_id)
    print(json.dumps(finding, indent=2))
    rows = flagged_rows(args.findings, findings, finding)
    print(f"\nFlags-table rows for its {len(rows)} entries:")
    if rows:
        print(pd.DataFrame(rows).to_string(index=False))


def command_ask(args) -> None:
    findings = load_findings(args.findings)
    finding = find(findings, args.finding_id)
    reference = findings["reference"]["label"]
    comparison = findings["comparison"]["label"]
    labels = read_labels(args.labels, [reference, comparison])
    revision = resolve_revision(args, labels, reference, comparison)

    request = {
        "comparison": f"{comparison} (comparison) vs {reference} (reference)",
        "finding": finding,
        "flags_table_rows": flagged_rows(args.findings, findings, finding),
    }
    if not args.no_dialogue:
        if args.dry_run:
            print(expert_dialogue.dry_run_text(request, revision, labels,
                                               args.repo, args.model,
                                               args.effort))
            return
        base_path = new_output_base(args.findings, "dialogue", finding["id"])
        state, state_path = expert_dialogue.start_dialogue(
            request, revision, labels, base_path, args.repo, args.model,
            args.effort)
        log_dialogue(args, findings, finding, state, state_path)
        return

    answer = ask_expert(request, revision, labels, args.repo, args.model,
                        args.effort, args.dry_run)
    if args.dry_run:
        print(answer)
        return

    answer_base = new_output_base(args.findings, "expert", finding["id"])
    answer_path = answer_base.with_name(answer_base.name + ".md")
    answer_path.write_text(
        f"# coresoftware expert: {finding['id']} "
        f"({comparison} vs {reference})\n\n"
        f"Generated {now_utc()} with {args.model} via Claude Code CLI, "
        f"read-only in {args.repo.name}. Revisions: {json.dumps(revision)}. "
        "AI-generated hypotheses; verify the cited commits before acting.\n\n"
        + answer + "\n")
    append_event(args.findings, findings, {
        "type": "ask", "finding": finding["id"], "time": now_utc(),
        "reviewer": args.reviewer, "revision": json.dumps(revision),
        "answer_file": answer_path.name})
    print(f"Wrote {answer_path}")


def log_dialogue(args, findings: dict, finding: dict, state: dict,
                 state_path: Path, continued: bool = False) -> None:
    append_event(args.findings, findings, {
        "type": "dialogue", "finding": finding["id"], "time": now_utc(),
        "reviewer": args.reviewer, "continued": continued,
        "state_file": state_path.name, "transcript_file": state["transcript"],
        "round": state["round"], "status": state["status"],
        "question_for_human": state["question_for_human"]})
    print(f"Dialogue {DIALOGUE_STATUS_TEXT.get(state['status'], state['status'])}"
          f" (round {state['round']}, turns this round: "
          f"{state['turns_this_round']}). Transcript: "
          f"{state_path.with_name(state['transcript'])}")
    if state["question_for_human"]:
        print(f"Question for you: {state['question_for_human']}")


def command_continue(args) -> None:
    findings = load_findings(args.findings)
    finding = find(findings, args.finding_id)
    dialogues = [event for event in load_log(args.findings)
                 if event["finding"] == finding["id"]
                 and event["type"] == "dialogue"]
    if not dialogues:
        sys.exit(f"ERROR: no expert dialogue for {finding['id']}; run "
                 "`review.py ask` first.")
    state_path = args.findings.with_name(dialogues[-1]["state_file"])
    try:
        state = expert_dialogue.continue_dialogue(state_path, args.note)
    except ValueError as error:
        sys.exit(f"ERROR: {error}; start a new one with `review.py ask`.")
    log_dialogue(args, findings, finding, state, state_path, continued=True)


def command_check(args) -> None:
    findings = load_findings(args.findings)
    finding = find(findings, args.finding_id)
    if args.answer:
        answer_path = args.answer
    else:
        answers = [event for event in load_log(args.findings)
                   if event["finding"] == finding["id"]
                   and event["type"] in ("ask", "dialogue")]
        if not answers:
            sys.exit(f"ERROR: no coresoftware expert answer for "
                     f"{finding['id']}; run `review.py ask` first or pass "
                     "--answer FILE.")
        latest = answers[-1]
        answer_path = args.findings.with_name(
            latest.get("answer_file") or latest["transcript_file"])
    if not answer_path.exists():
        sys.exit(f"ERROR: answer file {answer_path} not found.")

    request = {
        "comparison": f"{findings['comparison']['label']} (comparison) vs "
                      f"{findings['reference']['label']} (reference)",
        "finding": finding,
        "flags_table_rows": flagged_rows(args.findings, findings, finding),
    }
    review = check_answer(request, answer_path.read_text(), args.repo,
                          args.model, args.effort, args.dry_run)
    if args.dry_run:
        print(review)
        return

    check_base = new_output_base(args.findings, "check", finding["id"])
    check_path = check_base.with_name(check_base.name + ".md")
    check_path.write_text(
        f"# Tracking expert check: {finding['id']} of {answer_path.name}\n\n"
        f"Generated {now_utc()} with {args.model} via Claude Code CLI, "
        "read-only, against ACTS and Millepede-II documentation "
        "(tracking_docs/SOURCES.json). AI-generated; verify cited sources "
        "before acting.\n\n" + review + "\n")
    append_event(args.findings, findings, {
        "type": "check", "finding": finding["id"], "time": now_utc(),
        "reviewer": args.reviewer, "answer_file": answer_path.name,
        "check_file": check_path.name})
    print(f"Wrote {check_path}")


def command_decide(args) -> None:
    findings = load_findings(args.findings)
    finding = find(findings, args.finding_id)
    append_event(args.findings, findings, {
        "type": "decision", "finding": finding["id"], "time": now_utc(),
        "reviewer": args.reviewer, "decision": args.decision,
        "note": args.note})
    print(f"Recorded {args.decision} for {finding['id']}.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reviewer", default=getpass.getuser())
    commands = parser.add_subparsers(dest="command", required=True)

    list_parser = commands.add_parser("list")
    list_parser.add_argument("findings", type=Path)
    list_parser.set_defaults(handler=command_list)

    show_parser = commands.add_parser("show")
    show_parser.add_argument("findings", type=Path)
    show_parser.add_argument("finding_id")
    show_parser.set_defaults(handler=command_show)

    ask_parser = commands.add_parser("ask")
    ask_parser.add_argument("findings", type=Path)
    ask_parser.add_argument("finding_id")
    ask_parser.add_argument(
        "--labels", type=Path, default=Path("labels.csv"),
        help="label configuration (see maps/labels.example.csv)")
    ask_parser.add_argument("--from", dest="from_rev")
    ask_parser.add_argument("--to", dest="to_rev")
    ask_parser.add_argument("--since", help="YYYY-MM-DD")
    ask_parser.add_argument("--until", help="YYYY-MM-DD")
    ask_parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    ask_parser.add_argument("--model", default=DEFAULT_MODEL)
    ask_parser.add_argument("--effort", default="high",
                            choices=["low", "medium", "high", "xhigh", "max"])
    ask_parser.add_argument("--dry-run", action="store_true")
    ask_parser.add_argument("--no-dialogue", action="store_true",
                            help="single coresoftware expert answer, no "
                                 "dialogue with the tracking expert")
    ask_parser.set_defaults(handler=command_ask)

    continue_parser = commands.add_parser("continue")
    continue_parser.add_argument("findings", type=Path)
    continue_parser.add_argument("finding_id")
    continue_parser.add_argument("--note", default="",
                                 help="your reply or guidance, sent to both "
                                      "experts")
    continue_parser.set_defaults(handler=command_continue)

    check_parser = commands.add_parser("check")
    check_parser.add_argument("findings", type=Path)
    check_parser.add_argument("finding_id")
    check_parser.add_argument("--answer", type=Path,
                              help="expert answer to check (default: latest)")
    check_parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    check_parser.add_argument("--model", default=DEFAULT_MODEL)
    check_parser.add_argument("--effort", default="high",
                              choices=["low", "medium", "high", "xhigh", "max"])
    check_parser.add_argument("--dry-run", action="store_true")
    check_parser.set_defaults(handler=command_check)

    decide_parser = commands.add_parser("decide")
    decide_parser.add_argument("findings", type=Path)
    decide_parser.add_argument("finding_id")
    decide_parser.add_argument("decision",
                               choices=["accept", "reject", "needs-info"])
    decide_parser.add_argument("--note", default="")
    decide_parser.set_defaults(handler=command_decide)

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
