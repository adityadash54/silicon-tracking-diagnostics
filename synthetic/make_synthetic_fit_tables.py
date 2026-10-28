#!/usr/bin/env python3
"""Write synthetic layer-1 fit tables with known injected changes.

Produces residual_fits_<label>.csv files in the format written by
../macros/plot_fits_overlaid_stavechip.C, plus injections.csv describing every injected
change, so the comparison framework can be checked against a known answer.

Model per (label, detector, layer, stave, chip, coord):
  true mean  = baseline chip offset (shared by all labels) + injected offset
  true sigma = nominal width * per-chip spread (shared) * injected scale
  fitted mu, sigma = true values + Gaussian noise with the fit errors
  mu_err = sigma / sqrt(N),  sigma_err = sigma / sqrt(2 N)

Usage:
  python -m synthetic.make_synthetic_fit_tables [--out-dir DIR] [--seed 20261001]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

LABELS = {"Iter0": "ntuple_list1.txt", "Iter1": "ntuple_list2.txt",
          "Iter2": "ntuple_list3.txt"}
GEOMETRY = {  # detector: (layers, staves per layer, chips per stave)
    "MVTX": ([0, 1, 2], [12, 16, 20], 9),
    "INTT": ([3, 4, 5, 6], [12, 12, 16, 16], 4),
}
# Geometry and nominal widths come from public sPHENIX specifications: the
# widths are approximately pitch/sqrt(12) (ALPIDE 26.88 x 29.24 um pixels;
# INTT 78 um strip pitch, 16 mm strips for z), slightly widened for the track
# uncertainty. No real-data values are used. make_synthetic_ntp.C uses the
# same numbers.
NOMINAL_SIGMA_MM = {("MVTX", "rphi"): 0.007, ("MVTX", "z"): 0.008,
                    ("INTT", "rphi"): 0.025, ("INTT", "z"): 4.6}
NOMINAL_ENTRIES = {"MVTX": 3000, "INTT": 6000}
FIT_HALF_WIDTH_SIGMAS = 2.0

# Injected changes relative to Iter0. Selectors: None means "all".
# offset_mm adds to the true mean, sigma_scale multiplies the true width,
# entries overrides the entry count in every label, missing drops the rows.
INJECTIONS = [
    dict(name="stave_shift_rphi", labels=["Iter1"], detector="MVTX",
         layer=1, staves=[4], chips=None, coord="rphi", offset_mm=0.008,
         description="Whole MVTX stave displaced +8 um in local r-phi"),
    dict(name="chip_broadened", labels=["Iter1", "Iter2"], detector="MVTX",
         layer=0, staves=[2], chips=[5], coord=None, sigma_scale=1.40,
         description="One MVTX chip 40% broader in both coordinates"),
    dict(name="chip_shift_z", labels=["Iter1", "Iter2"], detector="MVTX",
         layer=2, staves=[10], chips=[3], coord="z", offset_mm=-0.012,
         description="One MVTX chip displaced -12 um in local z"),
    dict(name="sub_threshold_shift", labels=["Iter1"], detector="MVTX",
         layer=2, staves=[7], chips=[0], coord="rphi", offset_mm=0.003,
         description="Statistically significant +3 um shift below the "
                     "5 um minimum shift (must NOT be flagged)"),
    dict(name="intt_sensor_shift", labels=["Iter1"], detector="INTT",
         layer=4, staves=[6], chips=[1], coord="rphi", offset_mm=0.040,
         description="One INTT sensor displaced +40 um in local r-phi"),
    dict(name="low_stats_width", labels=["Iter1"], detector="MVTX",
         layer=0, staves=[9], chips=[8], coord="rphi", sigma_scale=1.30,
         entries=40,
         description="+30% width on a chip with only 40 entries per input "
                     "(statistically limited; may or may not be flagged)"),
    dict(name="low_stats_ladder", labels=["Iter0", "Iter1", "Iter2"],
         detector="INTT", layer=3, staves=[3], chips=None, coord=None,
         entries=5,
         description="INTT ladder with 5 entries per sensor in every input "
                     "(not comparable)"),
    dict(name="missing_ladder", labels=["Iter1"], detector="INTT",
         layer=5, staves=[9], chips=None, coord=None, missing=True,
         description="INTT ladder absent from Iter1 (not comparable)"),
    dict(name="half_layer_shift_z", labels=["Iter2"], detector="MVTX",
         layer=2, staves=list(range(10)), chips=None, coord="z",
         offset_mm=0.006,
         description="Half of MVTX layer 2 (staves 0-9) displaced +6 um in "
                     "local z"),
]


def matches(injection: dict, label: str, detector: str, layer: int,
            stave: int, chip: int, coord: str) -> bool:
    return (label in injection["labels"]
            and detector == injection["detector"]
            and layer == injection["layer"]
            and (injection["staves"] is None or stave in injection["staves"])
            and (injection["chips"] is None or chip in injection["chips"])
            and (injection["coord"] is None or coord == injection["coord"]))


def entries_override(detector, layer, stave, chip, coord,
                     injections: list[dict] | None = None):
    # Entry overrides apply to every label so both inputs share the statistics.
    for injection in INJECTIONS if injections is None else injections:
        if "entries" in injection and any(
                matches(injection, label, detector, layer, stave, chip, coord)
                for label in injection["labels"]):
            return injection["entries"]
    return None


def build_tables(seed: int, injections: list[dict] | None = None,
                 labels: dict[str, str] | None = None
                 ) -> dict[str, pd.DataFrame]:
    """Fit tables per label; defaults are the synthetic test's injections."""
    injections = INJECTIONS if injections is None else injections
    labels = LABELS if labels is None else labels
    rng = np.random.default_rng(seed)
    baseline = {}
    for detector, (layers, staves, chips) in GEOMETRY.items():
        for layer, stave_count in zip(layers, staves):
            for stave in range(stave_count):
                for chip in range(chips):
                    for coord in ("rphi", "z"):
                        nominal = NOMINAL_SIGMA_MM[(detector, coord)]
                        baseline[(detector, layer, stave, chip, coord)] = (
                            rng.normal(0.0, 0.25 * nominal),
                            nominal * rng.uniform(0.9, 1.1),
                            int(rng.poisson(NOMINAL_ENTRIES[detector])))

    tables = {}
    for label, listfile in labels.items():
        rows = []
        for key, (offset, sigma, entries) in baseline.items():
            detector, layer, stave, chip, coord = key
            active = [injection for injection in injections
                      if matches(injection, label, *key)]
            if any(injection.get("missing") for injection in active):
                continue
            true_mu = offset + sum(injection.get("offset_mm", 0.0)
                                   for injection in active)
            true_sigma = sigma * np.prod([injection.get("sigma_scale", 1.0)
                                          for injection in active])
            override = entries_override(*key, injections)
            n_entries = override if override is not None else int(
                rng.poisson(entries))

            core_entries = 0.95 * n_entries
            status = "ok" if core_entries >= 10 else "low_stats"
            mu_err = true_sigma / np.sqrt(core_entries)
            sigma_err = true_sigma / np.sqrt(2.0 * core_entries)
            if status == "ok":
                mu = true_mu + rng.normal(0.0, mu_err)
                fit_sigma = abs(true_sigma + rng.normal(0.0, sigma_err))
                chi2 = float(rng.chisquare(30))
                ndf = 30
                fit_low = mu - FIT_HALF_WIDTH_SIGMAS * fit_sigma
                fit_high = mu + FIT_HALF_WIDTH_SIGMAS * fit_sigma
            else:
                mu = mu_err = fit_sigma = sigma_err = chi2 = np.nan
                ndf = 0
                fit_low = fit_high = np.nan
            rows.append(dict(
                label=label, listfile=listfile, detector=detector,
                layer=layer, stave=stave, chip=chip, coord=coord,
                entries=n_entries, entries_in_fit_window=round(core_entries),
                populated_bins=min(n_entries, 60), fit_status=status,
                mu_mm=mu, mu_err_mm=mu_err, sigma_mm=fit_sigma,
                sigma_err_mm=sigma_err, chi2=chi2, ndf=ndf,
                fit_low_mm=fit_low, fit_high_mm=fit_high))
        tables[label] = pd.DataFrame(rows)
    return tables


def injection_table() -> pd.DataFrame:
    rows = []
    for injection in INJECTIONS:
        rows.append(dict(
            name=injection["name"], labels=";".join(injection["labels"]),
            detector=injection["detector"], layer=injection["layer"],
            staves="all" if injection["staves"] is None else
            ";".join(map(str, injection["staves"])),
            chips="all" if injection["chips"] is None else
            ";".join(map(str, injection["chips"])),
            coord=injection["coord"] or "both",
            offset_mm=injection.get("offset_mm", 0.0),
            sigma_scale=injection.get("sigma_scale", 1.0),
            entries=injection.get("entries", ""),
            missing=injection.get("missing", False),
            description=injection["description"]))
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("output"))
    parser.add_argument("--seed", type=int, default=20261001)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for label, table in build_tables(args.seed).items():
        path = args.out_dir / f"residual_fits_{label}.csv"
        table.to_csv(path, index=False, float_format="%.8g")
        print(f"Wrote {len(table)} rows to {path}")
    injection_path = args.out_dir / "injections.csv"
    injection_table().to_csv(injection_path, index=False)
    print(f"Wrote {len(INJECTIONS)} injections to {injection_path}")


if __name__ == "__main__":
    main()
