"""The committed reference of the synthetic pipeline (no ROOT needed)."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from synthetic.compare_to_reference import REFERENCE_DIR, compare_table
from synthetic.make_synthetic_fit_tables import injection_table
from synthetic.stavechip_demo.check_demo import check_flags, check_vertex_fits
from tests.conftest import REPO_ROOT, run_module

LABELS = ("Iter0", "Iter1", "Iter2")
DEMO_REFERENCE = REPO_ROOT / "synthetic" / "stavechip_demo" / "reference"


@pytest.fixture(scope="module")
def reference_comparison(tmp_path_factory):
    """compare_runs on the reference fit tables."""
    out = tmp_path_factory.mktemp("reference")
    run_module("stdiag.compare_runs",
               *(str(REFERENCE_DIR / f"residual_fits_{label}.csv")
                 for label in LABELS), "--out-dir", str(out))
    return out


def test_injections_match_generator():
    committed = (REFERENCE_DIR / "injections.csv").read_text()
    assert committed == injection_table().to_csv(index=False)


@pytest.mark.parametrize("comparison, flagged, not_comparable", [
    ("Iter1", 17, 19), ("Iter2", 105, 9)])
def test_reference_matches_injected_truth(reference_comparison, comparison,
                                          flagged, not_comparable):
    stem = f"Iter0_vs_{comparison}"
    output = run_module("synthetic.check_against_truth",
                        str(reference_comparison / f"flags_{stem}.csv"),
                        str(reference_comparison / f"summary_{stem}.json"))
    assert "PASS: all 1550 rows" in output
    counts = json.loads((reference_comparison / f"summary_{stem}.json")
                        .read_text())["counts"]
    assert (counts["flagged"], counts["not_comparable"]) == (
        flagged, not_comparable)


def test_compare_to_reference_detects_changes(tmp_path):
    reference = REFERENCE_DIR / "residual_fits_Iter1.csv"
    assert compare_table(reference, reference) == []

    table = pd.read_csv(reference, dtype={"detector": str, "coord": str})
    first_ok = table.index[table["fit_status"] == "ok"][0]
    table.loc[first_ok, "mu_mm"] *= 1.01
    changed = tmp_path / reference.name
    table.to_csv(changed, index=False, float_format="%.10g")
    problems = compare_table(changed, reference)
    assert len(problems) == 1 and problems[0].startswith("mu_mm differs in 1")


@pytest.mark.parametrize("version, expected_problems", [
    ("after", 0), ("before", 4)])
def test_stavechip_demo_reference(tmp_path, version, expected_problems):
    """The current fit matches the demo truth; the old settings miss the INTT
    z shift, flag two unshifted sensors and lose the +300 um chip."""
    tables = DEMO_REFERENCE / version
    run_module("stdiag.compare_runs", str(tables / "residual_fits_Iter0.csv"),
               str(tables / "residual_fits_Iter1.csv"), "--out-dir",
               str(tmp_path))
    flags = pd.read_csv(tmp_path / "flags_Iter0_vs_Iter1.csv",
                        dtype={"detector": str, "coord": str})
    assert len(check_flags(flags)) == expected_problems
    assert check_vertex_fits(tables) == []


def test_example_tables_in_inputs(tmp_path):
    """The committed example pair in inputs/ is the demo and passes its truth
    check; compare_runs files it under runs/example_iter0_vs_example_iter1."""
    inputs = REPO_ROOT / "inputs"
    output = run_module(
        "stdiag.compare_runs", str(inputs / "residual_fits_example_iter0.csv"),
        str(inputs / "residual_fits_example_iter1.csv"),
        env={"STDIAG_RUNS_DIR": str(tmp_path)})
    assert "Note:" not in output
    folder = tmp_path / "example_iter0_vs_example_iter1"
    flags = pd.read_csv(folder / "flags_example_iter0_vs_example_iter1.csv",
                        dtype={"detector": str, "coord": str})
    assert check_flags(flags) == []
