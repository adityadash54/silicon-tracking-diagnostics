#!/usr/bin/env python3
"""Check the stave/chip demo against the truth injected by make_synth.C.

Reads the flags table that stdiag.compare_runs wrote for Iter1 vs Iter0 and,
optionally, the vertex_phi_fit_<label>.csv tables, and compares them with
the expected result of the current fit macro:

  MVTX L0 stave 0 chip 3 r-phi  0 -> +10 um                    flagged
  MVTX chip 5 r-phi             +300 um -> 0 (outside the plot) flagged
  MVTX chip 7                   6 entries                     not comparable
  MVTX chip 8 r-phi             +800 um -> 0 (outside the
                                histogram range in Iter0)     not comparable
  INTT L3 ladder 0 sensor 2 z   0 -> +1.5 mm                  flagged
  every other chip, sensor and stave row                      unchanged
  VERTEX dca_xy phi bins        vertex offset (30, 0) -> (20, 10) um, so
                                Delta(-DCA_xy) = -10 sin(phi) - 10 cos(phi) um:
                                flagged where |Delta| is clearly above the
                                10 um minimum shift, unchanged where clearly
                                below, either way near it
  VERTEX chip -1 and all dca_z  unchanged
  vertex_phi_fit                A = 30 um, phi0 = 0 (Iter0); A = 22.4 um,
                                phi0 = 0.464 rad (Iter1)

On the tables made with the old fit settings (run_demo.sh "before") the
check fails, which is the point of that comparison.

Usage:
  python -m synthetic.stavechip_demo.check_demo FLAGS_CSV [--tables DIR]
Exit status is 1 if any entry disagrees.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

EXPECTED_SILICON = {
    ("MVTX", 3, "rphi"): "flagged",
    ("MVTX", 5, "rphi"): "flagged",
    ("MVTX", 7, "rphi"): "not_comparable",
    ("MVTX", 7, "z"): "not_comparable",
    ("MVTX", 8, "rphi"): "not_comparable",
    ("INTT", 2, "z"): "flagged",
}
VERTEX_SHIFT_UM = (-10.0, 10.0)   # change of (vertex - track origin), x and y
VERTEX_MIN_SHIFT_UM = 10.0
VERTEX_MARGIN_UM = 2.5            # about 1.5 times the per-bin uncertainty
PHI_BINS = 14
EXPECTED_VERTEX_FIT = {"Iter0": (30.0, 0.0), "Iter1": (22.4, 0.464)}
AMPLITUDE_TOLERANCE_UM = 1.5
PHASE_TOLERANCE_RAD = 0.06


def expected_vertex_status(phi_bin: int) -> tuple[str, float]:
    """Expected status and shift (um) of one dca_xy phi bin."""
    phi = -math.pi + (phi_bin + 0.5) * 2.0 * math.pi / PHI_BINS
    # -DCA_xy = vx sin(phi) - vy cos(phi), v = vertex - track origin.
    shift = VERTEX_SHIFT_UM[0] * math.sin(phi) - VERTEX_SHIFT_UM[1] * math.cos(phi)
    if abs(shift) > VERTEX_MIN_SHIFT_UM + VERTEX_MARGIN_UM:
        return "flagged", shift
    if abs(shift) < VERTEX_MIN_SHIFT_UM - VERTEX_MARGIN_UM:
        return "unchanged", shift
    return "either", shift


def expected_status(row: pd.Series) -> str:
    if row["detector"] == "VERTEX":
        if row["coord"] == "dca_xy" and row["chip"] >= 0:
            return expected_vertex_status(int(row["chip"]))[0]
        return "unchanged"
    return EXPECTED_SILICON.get(
        (row["detector"], int(row["chip"]), row["coord"]), "unchanged")


def check_flags(flags: pd.DataFrame) -> list[str]:
    """Return one line per row that disagrees with the truth."""
    problems = []
    for _, row in flags.iterrows():
        expected = expected_status(row)
        if expected != "either" and expected != row["comparison_status"]:
            problems.append(
                f"{row['detector']} L{row['layer']} S{row['stave']} "
                f"chip {row['chip']} {row['coord']}: expected {expected}, "
                f"got {row['comparison_status']} ({row['reason']})")
    return problems


def check_vertex_fits(tables: Path) -> list[str]:
    problems = []
    for label, (amplitude, phase) in EXPECTED_VERTEX_FIT.items():
        path = tables / f"vertex_phi_fit_{label}.csv"
        if not path.exists():
            problems.append(f"{path} does not exist")
            continue
        fit = pd.read_csv(path).iloc[0]
        got_amplitude = 1000.0 * fit["amplitude_mm"]
        if (fit["fit_status"] != "ok"
                or abs(got_amplitude - amplitude) > AMPLITUDE_TOLERANCE_UM
                or abs(fit["phi0_rad"] - phase) > PHASE_TOLERANCE_RAD):
            problems.append(
                f"{label} vertex fit: A = {got_amplitude:.1f} um, phi0 = "
                f"{fit['phi0_rad']:.3f} rad; expected {amplitude} um, "
                f"{phase} rad")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("flags", type=Path, help="flags_Iter0_vs_Iter1.csv")
    parser.add_argument("--tables", type=Path,
                        help="directory with vertex_phi_fit_<label>.csv")
    args = parser.parse_args()

    flags = pd.read_csv(args.flags, dtype={"detector": str, "coord": str})
    problems = check_flags(flags)
    if args.tables:
        problems += check_vertex_fits(args.tables)

    shown = flags.loc[flags["comparison_status"] != "unchanged",
                      ["detector", "layer", "stave", "chip", "coord",
                       "comparison_status", "reason"]]
    print(f"Entries that are not unchanged ({len(shown)} of {len(flags)}):")
    print(shown.to_string(index=False))
    if problems:
        print(f"\nFAIL: {len(problems)} disagreement(s) with the injected truth:")
        print("\n".join(f"  {problem}" for problem in problems))
        sys.exit(1)
    print(f"\nPASS: all {len(flags)} rows"
          + (" and both vertex fits" if args.tables else "")
          + " match the injected truth.")


if __name__ == "__main__":
    main()
