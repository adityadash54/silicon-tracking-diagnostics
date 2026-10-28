#!/usr/bin/env python3
"""Compare the fit tables of a synthetic pipeline run with the reference.

synthetic/run_full_pipeline.sh writes residual_fits_<label>.csv from the
synthetic ROOT files; synthetic/reference/ holds one committed set made the
same way (seed 20261001). Entry counts and fit statuses must match exactly
(ROOT's TRandom3 is deterministic for a given seed); fitted values must agree
within a relative tolerance, since fits can differ in the last digits between
ROOT versions and platforms.

Usage:
  python -m synthetic.compare_to_reference synthetic/pipeline_output
  python -m synthetic.compare_to_reference RUN_DIR --reference DIR
Exit status is 1 if any table differs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REFERENCE_DIR = Path(__file__).resolve().parent / "reference"
LABELS = ["Iter0", "Iter1", "Iter2"]
KEY = ["detector", "layer", "stave", "chip", "coord"]
EXACT_COLUMNS = ["entries", "fit_status"]
VALUE_COLUMNS = ["mu_mm", "mu_err_mm", "sigma_mm", "sigma_err_mm"]
RELATIVE_TOLERANCE = 1e-4
ABSOLUTE_TOLERANCE_MM = 1e-9


def compare_table(run: Path, reference: Path) -> list[str]:
    """Return the differences between two fit tables (empty if they agree)."""
    for path in (run, reference):
        if not path.exists():
            return [f"{path} does not exist"]
    columns = {"detector": str, "coord": str, "fit_status": str}
    new = pd.read_csv(run, dtype=columns).set_index(KEY).sort_index()
    old = pd.read_csv(reference, dtype=columns).set_index(KEY).sort_index()
    problems = []
    if not new.index.equals(old.index):
        missing = len(old.index.difference(new.index))
        extra = len(new.index.difference(old.index))
        return [f"rows differ ({missing} missing, {extra} extra)"]
    for column in EXACT_COLUMNS:
        differ = (new[column] != old[column]).sum()
        if differ:
            problems.append(f"{column} differs in {differ} rows")
    for column in VALUE_COLUMNS:
        close = np.isclose(new[column], old[column], rtol=RELATIVE_TOLERANCE,
                           atol=ABSOLUTE_TOLERANCE_MM, equal_nan=True)
        if not close.all():
            worst = (new[column] - old[column]).abs().max()
            problems.append(f"{column} differs in {(~close).sum()} rows "
                            f"(largest difference {worst:.3g} mm)")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--reference", type=Path, default=REFERENCE_DIR)
    args = parser.parse_args()

    failed = False
    for label in LABELS:
        name = f"residual_fits_{label}.csv"
        problems = compare_table(args.run_dir / name, args.reference / name)
        failed |= bool(problems)
        print(f"{name}: " + ("; ".join(problems) if problems else
                             "matches the reference"))
    if failed:
        print("The run differs from synthetic/reference/. With the same seed "
              "and macro version this points to a change in the generator, "
              "the fit macro or the ROOT version.")
        sys.exit(1)


if __name__ == "__main__":
    main()
