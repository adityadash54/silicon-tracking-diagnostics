#!/usr/bin/env python3
"""Layer 2: compare per-chip residual fits between inputs and flag changed chips.

Runs entirely locally: it reads the CSV tables written by
macros/plot_fits_overlaid_stavechip.C and writes CSV, JSON and Markdown files. It imports no
network libraries and sends nothing to any external service.

Criteria (input 1 = reference, input 2 = comparison), evaluated separately for
every (detector, layer, stave, chip, coord):
  width : |(sigma2 - sigma1) / sigma1| > --sigma-rel-threshold      (default 0.20)
  mean  : |mu2 - mu1| / sqrt(dmu1^2 + dmu2^2) > --z-threshold        (default 1.96)
          AND |mu2 - mu1| > minimum shift for (detector, coord)
  A chip is flagged if the width OR the mean criterion fires. Both fits must
  have fit_status == "ok"; anything else is reported as not comparable.
MVTX/INTT rows with chip = -1 are fits to the sum of all chips of the
stave/ladder ("stave rows"); they get the same criteria and minimum shifts as
the chips and are counted separately (level "stave") in the summary.

Usage:
  python -m stdiag.compare_runs residual_fits_Iter0.csv residual_fits_Iter1.csv \
      [residual_fits_Iter2.csv ...] [--out-dir DIR]
The first table is the reference; every other table is compared with it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# chip is the chip/sensor id for MVTX/INTT (-1 = whole stave/ladder) and the
# track-phi bin for VERTEX rows (-1 = all tracks, 0-13 = phi bins over
# [-pi, pi)).
KEY_COLUMNS = ["detector", "layer", "stave", "chip", "coord"]
STAVE_CHIP = -1
FIT_COLUMNS = [
    "entries", "entries_in_fit_window", "populated_bins", "fit_status",
    "mu_mm", "mu_err_mm", "sigma_mm", "sigma_err_mm", "chi2", "ndf",
    "fit_low_mm", "fit_high_mm",
]
REQUIRED_COLUMNS = ["label", "listfile", *KEY_COLUMNS, *FIT_COLUMNS]
TEXT_COLUMNS = {"label": str, "listfile": str, "detector": str, "coord": str,
                "fit_status": str}

DEFAULT_MIN_SHIFT_MM = {
    ("MVTX", "rphi"): 0.005,
    ("MVTX", "z"): 0.005,
    ("INTT", "rphi"): 0.020,
    ("INTT", "z"): 1.0,
    # Track-to-vertex residuals (-DCA) from track_ntp; their chip id is the
    # track-phi bin (chip -1 = all tracks, chip 0-13 = phi bins).
    ("VERTEX", "dca_xy"): 0.010,
    ("VERTEX", "dca_z"): 0.020,
}


def stave_row_mask(frame: pd.DataFrame) -> pd.Series:
    """True for MVTX/INTT whole-stave rows (chip = -1)."""
    return (frame["detector"] != "VERTEX") & (frame["chip"] == STAVE_CHIP)


def row_level(frame: pd.DataFrame) -> pd.Series:
    """Return the level of every row: chip, stave or vertex."""
    return pd.Series(
        np.select([frame["detector"] == "VERTEX", stave_row_mask(frame)],
                  ["vertex", "stave"], default="chip"),
        index=frame.index)


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sanitize_for_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", text) or "input"


def load_fit_table(path: Path) -> pd.DataFrame:
    table = pd.read_csv(path, dtype=TEXT_COLUMNS)
    missing = [column for column in REQUIRED_COLUMNS
               if column not in table.columns]
    if missing:
        sys.exit(f"ERROR: {path} is missing columns: {', '.join(missing)}")

    labels = table["label"].dropna().unique()
    if len(labels) != 1:
        sys.exit(f"ERROR: {path} must contain exactly one label, "
                 f"found {list(labels)}")
    if table.duplicated(KEY_COLUMNS).any():
        sys.exit(f"ERROR: {path} has duplicate (detector, layer, stave, chip, "
                 "coord) rows")
    return table


def parse_min_shift_overrides(overrides: list[str]) -> dict:
    minimum_shift = dict(DEFAULT_MIN_SHIFT_MM)
    for override in overrides:
        match = re.fullmatch(r"(\w+):(\w+)=([0-9.eE+-]+)", override)
        if not match or (match.group(1), match.group(2)) not in minimum_shift:
            valid = ", ".join(f"{detector}:{coord}"
                              for detector, coord in DEFAULT_MIN_SHIFT_MM)
            sys.exit(f"ERROR: --min-shift expects DETECTOR:COORD=MM with "
                     f"DETECTOR:COORD one of {valid} (e.g. INTT:z=0.5), "
                     f"got '{override}'")
        minimum_shift[(match.group(1), match.group(2))] = float(match.group(3))
    return minimum_shift


def describe_row(row: pd.Series, reference_label: str,
                 comparison_label: str) -> str:
    if not row["comparable"]:
        problems = [f"{label} {status}" for label, status in
                    ((reference_label, row["fit_status_1"]),
                     (comparison_label, row["fit_status_2"]))
                    if status != "ok"]
        return "not comparable: " + (", ".join(problems) or "invalid fit errors")

    parts = []
    if row["flag_mean"]:
        parts.append(f"mean shift {1000.0 * row['delta_mu_mm']:+.1f} um "
                     f"(z={row['mu_z']:.1f})")
    if row["flag_width"]:
        direction = "broader" if row["sigma_rel"] > 0 else "narrower"
        parts.append(f"width {100.0 * row['sigma_rel']:+.0f}% ({direction})")
    return "; ".join(parts)


def compare_tables(reference: pd.DataFrame, comparison: pd.DataFrame,
                   sigma_rel_threshold: float, z_threshold: float,
                   minimum_shift: dict) -> pd.DataFrame:
    reference_label = reference["label"].iloc[0]
    comparison_label = comparison["label"].iloc[0]
    merged = reference[KEY_COLUMNS + FIT_COLUMNS].merge(
        comparison[KEY_COLUMNS + FIT_COLUMNS], on=KEY_COLUMNS, how="outer",
        suffixes=("_1", "_2"))
    merged = merged.rename(columns={
        f"{column}{suffix}": f"{column.replace('_mm', '')}{suffix}_mm"
        if column.endswith("_mm") else f"{column}{suffix}"
        for column in FIT_COLUMNS for suffix in ("_1", "_2")})
    merged["fit_status_1"] = merged["fit_status_1"].fillna("missing")
    merged["fit_status_2"] = merged["fit_status_2"].fillna("missing")

    mu1, mu2 = merged["mu_1_mm"], merged["mu_2_mm"]
    mu_err1, mu_err2 = merged["mu_err_1_mm"], merged["mu_err_2_mm"]
    sigma1, sigma2 = merged["sigma_1_mm"], merged["sigma_2_mm"]
    sigma_err1, sigma_err2 = merged["sigma_err_1_mm"], merged["sigma_err_2_mm"]

    mu_err = np.sqrt(mu_err1 ** 2 + mu_err2 ** 2)
    merged["comparable"] = (
        (merged["fit_status_1"] == "ok") & (merged["fit_status_2"] == "ok")
        & (sigma1 > 0) & (sigma2 > 0) & np.isfinite(mu_err) & (mu_err > 0))

    with np.errstate(divide="ignore", invalid="ignore"):
        merged["delta_mu_mm"] = mu2 - mu1
        merged["mu_z"] = np.abs(mu2 - mu1) / mu_err
        merged["separation"] = np.abs(mu2 - mu1) / np.sqrt(
            sigma1 ** 2 + sigma2 ** 2)
        merged["sigma_rel"] = (sigma2 - sigma1) / sigma1
        sigma_rel_err = (sigma2 / sigma1) * np.sqrt(
            (sigma_err1 / sigma1) ** 2 + (sigma_err2 / sigma2) ** 2)
        merged["sigma_rel_err"] = sigma_rel_err
        merged["sigma_rel_significance"] = (
            np.abs(merged["sigma_rel"]) / sigma_rel_err)

    merged["min_shift_mm"] = [
        minimum_shift.get((detector, coord), np.nan)
        for detector, coord in zip(merged["detector"], merged["coord"])]
    merged["flag_mean"] = (
        merged["comparable"] & (merged["mu_z"] > z_threshold)
        & (np.abs(merged["delta_mu_mm"]) > merged["min_shift_mm"]))
    merged["flag_width"] = (
        merged["comparable"]
        & (np.abs(merged["sigma_rel"]) > sigma_rel_threshold))
    merged["flagged"] = merged["flag_mean"] | merged["flag_width"]
    merged["comparison_status"] = np.select(
        [~merged["comparable"], merged["flagged"]],
        ["not_comparable", "flagged"], default="unchanged")
    merged["reason"] = merged.apply(
        describe_row, axis=1, args=(reference_label, comparison_label))
    merged.insert(0, "comparison_label", comparison_label)
    merged.insert(0, "reference_label", reference_label)
    return merged.sort_values(KEY_COLUMNS).reset_index(drop=True)


def count_flags(frame: pd.DataFrame) -> dict:
    return {
        "rows": int(len(frame)),
        "comparable": int(frame["comparable"].sum()),
        "not_comparable": int((~frame["comparable"]).sum()),
        "flagged": int(frame["flagged"].sum()),
        "flag_mean": int(frame["flag_mean"].sum()),
        "flag_width": int(frame["flag_width"].sum()),
        "flag_mean_and_width": int(
            (frame["flag_mean"] & frame["flag_width"]).sum()),
    }


def build_summary(flags: pd.DataFrame, inputs: dict, criteria: dict) -> dict:
    # level keeps whole-stave rows out of the per-layer chip counts.
    levels = flags.assign(level=row_level(flags))
    by_layer = []
    for (detector, layer, coord, level), group in levels.groupby(
            ["detector", "layer", "coord", "level"], sort=True):
        by_layer.append({"detector": detector, "layer": int(layer),
                         "coord": coord, "level": level,
                         **count_flags(group)})
    by_level = {level: count_flags(group)
                for level, group in levels.groupby("level", sort=True)}

    not_comparable = (
        flags.loc[~flags["comparable"]]
        .groupby(["detector", "fit_status_1", "fit_status_2"])
        .size().reset_index(name="rows"))

    return {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"),
        "tool": "compare_runs.py",
        "inputs": inputs,
        "criteria": criteria,
        "counts": count_flags(flags),
        "counts_by_level": by_level,
        "by_detector_layer_coord": by_layer,
        "not_comparable_by_status": not_comparable.to_dict(orient="records"),
    }


def markdown_table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(value) for value in row) + " |"
              for row in rows]
    return "\n".join(lines)


def format_um(value_mm: float, digits: int = 1) -> str:
    return "" if pd.isna(value_mm) else f"{1000.0 * value_mm:.{digits}f}"


def build_report(flags: pd.DataFrame, summary: dict) -> str:
    reference = summary["inputs"]["reference"]
    comparison = summary["inputs"]["comparison"]
    criteria = summary["criteria"]
    counts = summary["counts"]

    sections = [
        f"# Residual comparison: {comparison['label']} vs "
        f"{reference['label']}",
        f"Generated {summary['generated_utc']} by compare_runs.py "
        "(deterministic, no AI).",
        "## Inputs and detector configuration",
        "Record the detector/reconstruction configuration of each label "
        "below (geometry/alignment tag, field, run conditions, track "
        "selection).",
        markdown_table(
            ["Role", "Label", "List file", "Fit table (sha256, first 12)",
             "Detector configuration (fill in)"],
            [["reference", reference["label"], reference["listfile"],
              f"{reference['csv']} ({reference['sha256'][:12]})", ""],
             ["comparison", comparison["label"], comparison["listfile"],
              f"{comparison['csv']} ({comparison['sha256'][:12]})", ""]]),
        "## Criteria",
        f"- Width: \\|(sigma2 - sigma1)/sigma1\\| > "
        f"{criteria['sigma_rel_threshold']}",
        f"- Mean: \\|mu2 - mu1\\| / sqrt(dmu1^2 + dmu2^2) > "
        f"{criteria['z_threshold']} and \\|mu2 - mu1\\| > minimum shift "
        "(" + ", ".join(f"{key} {1000.0 * value:g} um" for key, value in
                        criteria["min_shift_mm"].items()) + ")",
        "- Flagged if width OR mean fires; both fits must have status ok.",
        "## Counts",
        markdown_table(list(counts.keys()), [list(counts.values())]),
        markdown_table(
            ["Detector", "Layer", "Coord", "Level", "Comparable", "Flagged",
             "Mean", "Width", "Not comparable"],
            [[row["detector"], row["layer"], row["coord"], row["level"],
              row["comparable"], row["flagged"], row["flag_mean"],
              row["flag_width"], row["not_comparable"]]
             for row in summary["by_detector_layer_coord"]]),
    ]

    flagged = flags.loc[flags["flagged"]]
    sections.append(f"## Flagged entries ({len(flagged)})")
    if flagged.empty:
        sections.append("No entries passed the flagging criteria.")
    else:
        sections.append(markdown_table(
            ["Det", "Layer", "Stave", "Chip", "Coord", "dmu [um]", "z",
             "Separation", "sigma1 [um]", "sigma2 [um]", "sigma rel",
             "sigma rel signif.", "N1", "N2", "Reason"],
            [[row.detector, row.layer, row.stave, row.chip, row.coord,
              format_um(row.delta_mu_mm), f"{row.mu_z:.1f}",
              f"{row.separation:.2f}", format_um(row.sigma_1_mm),
              format_um(row.sigma_2_mm), f"{row.sigma_rel:+.2f}",
              f"{row.sigma_rel_significance:.1f}", f"{row.entries_1:.0f}",
              f"{row.entries_2:.0f}", row.reason]
             for row in flagged.itertuples()]))

    sections.append("## Not comparable")
    if summary["not_comparable_by_status"]:
        sections.append(markdown_table(
            ["Detector", f"{reference['label']} status",
             f"{comparison['label']} status", "Rows"],
            [[row["detector"], row["fit_status_1"], row["fit_status_2"],
              row["rows"]] for row in summary["not_comparable_by_status"]]))
    else:
        sections.append("All entries were comparable.")

    sections += [
        "## Caveats",
        "- About 1300 chip/coordinate tests (plus about 210 stave/ladder "
        "tests when the table has chip = -1 stave rows, and 30 VERTEX tests "
        "when track_ntp is present) are made per comparison; at z > 1.96 "
        "about 5% of unchanged entries pass the significance test by chance, "
        "so the minimum-shift requirement carries most of the rejection of "
        "chance flags.",
        "- MVTX/INTT rows with chip = -1 are fits to the sum of all chips of "
        "the stave/ladder, so they are not independent of the chip rows. A "
        "whole-stave shift moves the stave row and most chips together. A "
        "single chip shifted within the core of the stave distribution pulls "
        "the stave mean by about its share of the stave entries (about 1/9 "
        "of its shift for MVTX, 1/4 for INTT); a chip shifted beyond the core "
        "barely moves it. Stave rows have small errors, so the minimum shift "
        "decides most of their flags. INTT z stave rows sum the sensors' "
        "strip-length boxes and are only indicative.",
        "- VERTEX rows (layer = stave = -1) are track-to-vertex residuals "
        "whose chip id is the track-phi bin: chip -1 is the distribution of "
        "all tracks and chip 0-13 are equal track-phi bins over [-pi, pi), "
        "so they are not independent of each other. A transverse silicon-to-vertex offset appears as a "
        "sinusoidal dca_xy shift versus phi that can average to almost zero "
        "in chip -1. The vertex is reconstructed from the same tracks, which "
        "biases these residuals toward zero.",
        "- The width test has no significance requirement. Check the "
        "'sigma rel signif.' column: values below about 2 indicate a width "
        "change compatible with statistical fluctuation.",
        "- INTT z residuals are not Gaussian (strip length sets the width), "
        "so INTT z fit parameters are only indicative.",
        "- Different run conditions (field, luminosity, track momentum "
        "spectrum, track selection, alignment/geometry tag) change sigma "
        "without any detector change; compare like with like.",
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tables", nargs="+", type=Path,
                        help="residual_fits_<label>.csv files; first is the "
                             "reference")
    parser.add_argument("--out-dir", type=Path, default=Path("."))
    parser.add_argument("--sigma-rel-threshold", type=float, default=0.20)
    parser.add_argument("--z-threshold", type=float, default=1.96)
    parser.add_argument("--min-shift", action="append", default=[],
                        metavar="DETECTOR:COORD=MM",
                        help="override a minimum mean shift, e.g. "
                             "INTT:z=0.5 or VERTEX:dca_xy=0.02 (repeatable)")
    args = parser.parse_args()

    if len(args.tables) < 2:
        sys.exit("ERROR: give at least two fit tables (reference first)")

    minimum_shift = parse_min_shift_overrides(args.min_shift)
    tables = [load_fit_table(path) for path in args.tables]
    labels = [table["label"].iloc[0] for table in tables]
    if len(set(labels)) != len(labels):
        sys.exit(f"ERROR: input labels must be distinct, got {labels}")

    criteria = {
        "sigma_rel_threshold": args.sigma_rel_threshold,
        "z_threshold": args.z_threshold,
        "min_shift_mm": {f"{detector}:{coord}": value for
                         (detector, coord), value in minimum_shift.items()},
        "logic": "flagged = width OR (z AND minimum shift); "
                 "reference = first table",
    }

    def describe_input(path: Path, table: pd.DataFrame) -> dict:
        return {"label": table["label"].iloc[0],
                "listfile": table["listfile"].iloc[0],
                "csv": path.name, "sha256": sha256sum(path)}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    reference = tables[0]
    for path, comparison in zip(args.tables[1:], tables[1:]):
        flags = compare_tables(reference, comparison,
                               args.sigma_rel_threshold, args.z_threshold,
                               minimum_shift)
        inputs = {"reference": describe_input(args.tables[0], reference),
                  "comparison": describe_input(path, comparison)}
        summary = build_summary(flags, inputs, criteria)

        stem = (f"{sanitize_for_filename(inputs['reference']['label'])}_vs_"
                f"{sanitize_for_filename(inputs['comparison']['label'])}")
        flags_path = args.out_dir / f"flags_{stem}.csv"
        summary_path = args.out_dir / f"summary_{stem}.json"
        report_path = args.out_dir / f"report_{stem}.md"
        flags.to_csv(flags_path, index=False)
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")
        report_path.write_text(build_report(flags, summary))

        counts = summary["counts"]
        print(f"{inputs['comparison']['label']} vs "
              f"{inputs['reference']['label']}: {counts['flagged']} flagged "
              f"of {counts['comparable']} comparable "
              f"({counts['not_comparable']} not comparable) -> "
              f"{flags_path}, {summary_path}, {report_path}")


if __name__ == "__main__":
    main()
