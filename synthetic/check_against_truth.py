#!/usr/bin/env python3
"""Check compare_runs.py flags against the known synthetic injections.

For every row of a flags_<A>_vs_<B>.csv file, the expected comparison status
is derived from the true injected changes in make_synthetic_fit_tables.py and
the thresholds recorded in the matching summary JSON. Rows with an injected
low-statistics change are expected to be "either" (statistically limited).
It works on the tables of make_synthetic_fit_tables.py and on those that
macros/plot_fits_overlaid_stavechip.C writes from make_synthetic_ntp.C: their
whole-stave rows (chip = -1) are checked against the average change of the
stave's chips (see expected_stave_status), and VERTEX rows, which have no
injected change, are expected unchanged.

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

from synthetic.make_synthetic_fit_tables import (
    GEOMETRY, INJECTIONS, NOMINAL_SIGMA_MM, matches)

LOW_STATS_ENTRIES = 200
STAVE_CHIP = -1
# A stave row with only some of its chips changed is "either" when its
# approximate change is within this range of a threshold (as a fraction of it).
PARTIAL_STAVE_BAND = (0.5, 1.5)


def injected_state(label: str, key: tuple) -> tuple[float, float, bool, int]:
    active = [injection for injection in INJECTIONS
              if matches(injection, label, *key)]
    offset = sum(injection.get("offset_mm", 0.0) for injection in active)
    scale = float(np.prod([injection.get("sigma_scale", 1.0)
                           for injection in active]))
    missing = any(injection.get("missing") for injection in active)
    # An entry override covers the whole chip in every label: in ntp a
    # cluster carries both residuals, so it applies to both coordinates.
    entries = min([injection["entries"] for injection in INJECTIONS
                   if "entries" in injection and any(
                       matches(injection, other, *key[:4],
                               injection["coord"] or key[4])
                       for other in injection["labels"])], default=0)
    return offset, scale, missing, entries


def expected_stave_status(key: tuple, reference: str, comparison: str,
                          criteria: dict) -> str:
    """Expected status of a whole-stave row (chip = -1, the fit to the sum of
    the stave's chips), from equal-entry averages over its chips: the mean is
    the average chip offset and the variance adds the spread of the chip
    offsets. This is approximate when only some chips change, so such rows are
    "either" near a threshold."""
    detector, layer, stave, _, coord = key
    states = {label: [injected_state(label, (detector, layer, stave, chip,
                                             coord))
                      for chip in range(GEOMETRY[detector][2])]
              for label in (reference, comparison)}
    missing = [[state[2] for state in chips] for chips in states.values()]
    if any(all(chips) for chips in missing):
        return "not_comparable"
    if any(any(chips) for chips in missing) or any(
            state[3] for chips in states.values() for state in chips):
        return "either"

    nominal = NOMINAL_SIGMA_MM[(detector, coord)]

    def moments(chips):
        offsets = np.array([state[0] for state in chips])
        scales = np.array([state[1] for state in chips])
        return offsets.mean(), nominal ** 2 * np.mean(scales ** 2) + offsets.var()

    mean_1, variance_1 = moments(states[reference])
    mean_2, variance_2 = moments(states[comparison])
    shift = (abs(mean_2 - mean_1)
             / criteria["min_shift_mm"][f"{detector}:{coord}"])
    width = (abs(np.sqrt(variance_2 / variance_1) - 1.0)
             / criteria["sigma_rel_threshold"])
    partial = any(len({state[:2] for state in chips}) > 1
                  for chips in states.values())
    low, high = PARTIAL_STAVE_BAND
    if partial and any(low <= ratio <= high for ratio in (shift, width)):
        return "either"
    return "flagged" if shift > 1.0 or width > 1.0 else "unchanged"


def expected_status(row: pd.Series, reference: str, comparison: str,
                    criteria: dict) -> str:
    key = (row["detector"], int(row["layer"]), int(row["stave"]),
           int(row["chip"]), row["coord"])
    if key[0] != "VERTEX" and key[3] == STAVE_CHIP:
        return expected_stave_status(key, reference, comparison, criteria)
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
