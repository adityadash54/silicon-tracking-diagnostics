"""The steps without AI: fit tables -> flags, checked against injected truth."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from stdiag.compare_runs import build_summary, parse_min_shift_overrides
from tests.conftest import run_module


@pytest.mark.parametrize("comparison", ["Iter1", "Iter2"])
def test_flags_match_injected_truth(synthetic_outputs, comparison):
    stem = f"Iter0_vs_{comparison}"
    output = run_module("synthetic.check_against_truth",
                        str(synthetic_outputs / f"flags_{stem}.csv"),
                        str(synthetic_outputs / f"summary_{stem}.json"))
    assert "PASS" in output


def test_expected_counts(synthetic_outputs):
    counts = {comparison: json.loads((synthetic_outputs /
              f"summary_Iter0_vs_{comparison}.json").read_text())["counts"]
              for comparison in ("Iter1", "Iter2")}
    assert (counts["Iter1"]["flagged"], counts["Iter1"]["not_comparable"]) == (13, 16)
    assert (counts["Iter2"]["flagged"], counts["Iter2"]["not_comparable"]) == (93, 8)


def test_sub_threshold_shift_is_significant_but_not_flagged(synthetic_outputs):
    flags = pd.read_csv(synthetic_outputs / "flags_Iter0_vs_Iter1.csv")
    row = flags.query("detector == 'MVTX' and layer == 2 and stave == 7 "
                      "and chip == 0 and coord == 'rphi'").iloc[0]
    assert row["mu_z"] > 5 and not row["flagged"]


def test_report_carries_label_configuration_table(synthetic_outputs):
    report = (synthetic_outputs / "report_Iter0_vs_Iter1.md").read_text()
    assert "Detector configuration (fill in)" in report
    assert "| reference | Iter0 | ntuple_list1.txt" in report


def test_summary_keeps_stave_rows_apart(flags_with_stave_rows):
    flags, _ = flags_with_stave_rows
    without_stave_rows = flags.loc[(flags["chip"] >= 0)
                                   | (flags["detector"] == "VERTEX")]
    summary = build_summary(flags, {}, {})
    reference = build_summary(without_stave_rows, {}, {})

    assert summary["counts_by_level"]["stave"]["rows"] == 2
    assert summary["counts_by_level"]["stave"]["flagged"] == 2
    assert (summary["counts_by_level"]["chip"]
            == reference["counts_by_level"]["chip"])

    def chip_level(rows):
        return [row for row in rows if row["level"] == "chip"]

    assert (chip_level(summary["by_detector_layer_coord"])
            == chip_level(reference["by_detector_layer_coord"]))


def test_min_shift_override():
    shifts = parse_min_shift_overrides(["INTT:z=0.5"])
    assert shifts[("INTT", "z")] == 0.5 and shifts[("MVTX", "rphi")] == 0.005
    with pytest.raises(SystemExit):
        parse_min_shift_overrides(["TPC:z=1"])
