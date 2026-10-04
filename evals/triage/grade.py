"""Code-only grading of triage findings against a case's injected truth.

Rules (approved in PROPOSED_CASES.md):
- An injection is matched when one finding holds at least 80% of the
  injection's flagged rows and at least 80% of that finding's flagged rows
  come from it.
- pass: validation passed, every flag-producing injection matched by a
  finding with its expected group, no false findings, no merges.
- false finding: a finding in groups A-D whose rows are mostly (more than
  half) not flagged rows of any injection.
- merged: a finding that holds at least half of the flagged rows of two or
  more different injections.
Injections expected to produce no flags (expected None) and statistically
limited ones (expected "either") are never required; rows of "either"
injections count as injection rows, so findings about them are not false.
"""

from __future__ import annotations

import pandas as pd

from synthetic.make_synthetic_fit_tables import matches

KEY = ["detector", "layer", "stave", "chip", "coord"]
FLAG_GROUPS = {"A", "B", "C", "D"}
MATCH_FRACTION = 0.8
MERGE_FRACTION = 0.5


def key_of(values) -> tuple:
    detector, layer, stave, chip, coord = values
    return (str(detector), int(layer), int(stave), int(chip), str(coord))


def injection_rows(injection: dict, flagged: set[tuple]) -> set[tuple]:
    return {row for row in flagged
            if any(matches(injection, label, *row)
                   for label in injection["labels"])}


def grade(case: dict, flags: pd.DataFrame, findings: dict) -> dict:
    """Return {"grade": {...}, "meta": {...}} for one triage run."""
    flagged = {key_of(row) for row in
               flags.loc[flags["flagged"], KEY].itertuples(index=False)}
    required, tolerated = [], set()
    for injection in case["injections"]:
        rows = injection_rows(injection, flagged)
        if injection["expected"] in FLAG_GROUPS and rows:
            required.append((injection, rows))
        elif injection["expected"] == "either":
            tolerated |= rows
    injected_rows = set().union(tolerated, *(rows for _, rows in required))

    finding_list = findings.get("findings") or []
    entries = []
    for finding in finding_list:
        keys = set()
        for entry in finding.get("entries", []):
            try:
                keys.add(key_of([entry.get(column) for column in KEY]))
            except (TypeError, ValueError):
                continue
        entries.append(keys)

    details, matched, group_correct = [], 0, 0
    for injection, rows in required:
        best = None
        for finding, keys in zip(finding_list, entries):
            covered = rows & keys
            finding_flagged = keys & flagged
            if (len(covered) >= MATCH_FRACTION * len(rows) and finding_flagged
                    and len(covered) >= MATCH_FRACTION * len(finding_flagged)):
                best = finding
                break
        group = best.get("group") if best else None
        matched += best is not None
        group_correct += group == injection["expected"]
        details.append({"injection": injection["name"],
                        "expected": injection["expected"],
                        "flagged_rows": len(rows),
                        "matched_finding": best.get("id") if best else None,
                        "group": group})

    false_findings = [
        finding.get("id") for finding, keys in zip(finding_list, entries)
        if finding.get("group") in FLAG_GROUPS
        and (not keys or len(keys & injected_rows) <= 0.5 * len(keys))]
    merged = [
        finding.get("id") for finding, keys in zip(finding_list, entries)
        if sum(len(rows & keys) >= MERGE_FRACTION * len(rows)
               for _, rows in required) >= 2]

    validation = bool(findings.get("validation", {}).get("passed"))
    passed = (validation and matched == len(required)
              and group_correct == len(required)
              and not false_findings and not merged)
    scores = {"pass": float(passed),
              "false_findings": float(len(false_findings)),
              "merged": float(len(merged)),
              "validation": float(validation)}
    if required:
        scores["recall"] = matched / len(required)
        scores["group_acc"] = group_correct / matched if matched else 0.0
    return {"grade": scores,
            "meta": {"required_injections": len(required),
                     "matched": matched, "group_correct": group_correct,
                     "false_findings": false_findings, "merged": merged,
                     "injections": details, "findings": len(finding_list)}}
