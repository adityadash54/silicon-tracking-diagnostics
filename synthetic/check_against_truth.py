#!/usr/bin/env python3
"""Check compare_runs.py flags against the known synthetic injections.

For every row of a flags_<A>_vs_<B>.csv file, the expected comparison status
is derived from the true injected changes in make_synthetic_fit_tables.py and
the thresholds recorded in the matching summary JSON. Rows with an injected
low-statistics change are expected to be "either" (statistically limited).

Usage:
  python -m synthetic.check_against_truth output/flags_Iter0_vs_Iter1.csv \
      output/summary_Iter0_vs_Iter1.json
Exit status is 1 if any row disagrees with the expectation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from synthetic.make_synthetic_fit_tables import INJECTIONS, matches

LOW_STATS_ENTRIES = 200


def injected_state(label: str, key: tuple) -> tuple[float, float, bool, int]:
    active = [injection for injection in INJECTIONS
              if matches(injection, label, *key)]
    offset = sum(injection.get("offset_mm", 0.0) for injection in active)
    scale = float(np.prod([injection.get("sigma_scale", 1.0)
                           for injection in active]))
    missing = any(injection.get("missing") for injection in active)
    entries = min([injection["entries"] for injection in INJECTIONS
                   if "entries" in injection and any(
                       matches(injection, other, *key)
                       for other in injection["labels"])], default=0)
    return offset, scale, missing, entries


def expected_status(row: pd.Series, reference: str, comparison: str,
                    criteria: dict) -> str:
    key = (row["detector"], int(row["layer"]), int(row["stave"]),
           int(row["chip"]), row["coord"])
    offset1, scale1, missing1, entries = injected_state(reference, key)
    offset2, scale2, missing2, _ = injected_state(comparison, key)
    if missing1 or missing2 or (entries and 0.95 * entries < 10):
        return "not_comparable"

    if entries and entries < LOW_STATS_ENTRIES:
        # Width fluctuations of ~1/sqrt(2N) can cross the threshold either way.
        return "either"

    min_shift = criteria["min_shift_mm"][f"{key[0]}:{key[4]}"]
    mean_change = abs(offset2 - offset1) > min_shift
    width_change = abs(scale2 / scale1 - 1.0) > criteria["sigma_rel_threshold"]
    return "flagged" if mean_change or width_change else "unchanged"


def injection_names(row: pd.Series, reference: str, comparison: str) -> str:
    key = (row["detector"], int(row["layer"]), int(row["stave"]),
           int(row["chip"]), row["coord"])
    return ";".join(injection["name"] for injection in INJECTIONS
                    if matches(injection, reference, *key)
                    or matches(injection, comparison, *key))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("flags", type=Path)
    parser.add_argument("summary", type=Path)
    args = parser.parse_args()

    flags = pd.read_csv(args.flags, dtype={"detector": str, "coord": str})
    summary = json.loads(args.summary.read_text())
    reference = summary["inputs"]["reference"]["label"]
    comparison = summary["inputs"]["comparison"]["label"]

    flags["expected"] = flags.apply(
        expected_status, axis=1,
        args=(reference, comparison, summary["criteria"]))
    flags["injections"] = flags.apply(
        injection_names, axis=1, args=(reference, comparison))
    agrees = ((flags["expected"] == "either")
              | (flags["expected"] == flags["comparison_status"]))

    print(f"== {comparison} vs {reference} ==")
    print(pd.crosstab(flags["expected"], flags["comparison_status"],
                      margins=True).to_string())
    injected = flags.loc[flags["injections"] != ""]
    if not injected.empty:
        print("\nPer injection (rows: observed status counts):")
        per_injection = (injected.groupby(["injections", "comparison_status"])
                         .size().unstack(fill_value=0))
        print(per_injection.to_string())

    mismatches = flags.loc[~agrees]
    if mismatches.empty:
        print(f"\nPASS: all {len(flags)} rows match the injected truth.")
        return
    print(f"\nFAIL: {len(mismatches)} rows disagree with the injected truth:")
    print(mismatches[["detector", "layer", "stave", "chip", "coord",
                      "expected", "comparison_status", "reason",
                      "injections"]].to_string(index=False))
    sys.exit(1)


if __name__ == "__main__":
    main()
