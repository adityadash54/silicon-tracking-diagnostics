"""The 21 triage eval cases approved in PROPOSED_CASES.md.

Each case compares a reference ("Ref") with a comparison ("Cmp") built by
synthetic.make_synthetic_fit_tables with the listed injections. `expected`
is the triage group a matched finding must have: A (coherent stave-wide
mean shift), B (isolated chip/sensor mean shift), C (width only), D (mean
and width), None (should produce no flags, e.g. not comparable or below
threshold), or "either" (statistically limited; never penalised).
"""

from __future__ import annotations

LABELS = {"Ref": "ref.txt", "Cmp": "cmp.txt"}
CMP = ["Cmp"]
BOTH = ["Ref", "Cmp"]


def inject(name, detector, layer, staves, chips=None, coord=None, *,
           expected, labels=CMP, **change):
    return {"name": name, "labels": labels, "detector": detector,
            "layer": layer, "staves": staves, "chips": chips, "coord": coord,
            "expected": expected, "description": name, **change}


LOW_STATS_LADDER = inject("low_stats_ladder", "INTT", 3, [3], labels=BOTH,
                          entries=5, expected=None)
MISSING_LADDER = inject("missing_ladder", "INTT", 5, [9], missing=True,
                        expected=None)
# The entry override applies to every label (see the generator); the width
# change applies to the comparison only.
LOW_STATS_WIDTH = inject("low_stats_width", "MVTX", 0, [9], [8], "rphi",
                         entries=40, sigma_scale=1.3, expected="either")

CASES = [
    {"id": "null-1", "tag": "null", "seed": 101, "injections": []},
    {"id": "null-2", "tag": "null", "seed": 102, "injections": []},
    {"id": "null-3", "tag": "null", "seed": 103,
     "injections": [LOW_STATS_LADDER]},
    {"id": "stave-mvtx-rphi", "tag": "stave", "seed": 201, "injections": [
        inject("stave_rphi", "MVTX", 1, [4], coord="rphi", offset_mm=0.008,
               expected="A")]},
    {"id": "stave-mvtx-z", "tag": "stave", "seed": 202, "injections": [
        inject("stave_z", "MVTX", 0, [7], coord="z", offset_mm=-0.012,
               expected="A")]},
    {"id": "stave-intt-rphi", "tag": "stave", "seed": 203, "injections": [
        inject("ladder_rphi", "INTT", 5, [3], coord="rphi", offset_mm=0.035,
               expected="A")]},
    {"id": "half-layer-z", "tag": "stave", "seed": 204, "injections": [
        inject("half_layer_z", "MVTX", 2, list(range(10)), coord="z",
               offset_mm=0.006, expected="A")]},
    {"id": "whole-layer-rphi", "tag": "stave", "seed": 205, "injections": [
        inject("whole_layer_rphi", "MVTX", 1, None, coord="rphi",
               offset_mm=0.007, expected="A")]},
    {"id": "opposite-staves", "tag": "stave", "seed": 206, "injections": [
        inject("stave4_plus", "MVTX", 1, [4], coord="rphi", offset_mm=0.008,
               expected="A"),
        inject("stave5_minus", "MVTX", 1, [5], coord="rphi",
               offset_mm=-0.008, expected="A")]},
    {"id": "chip-mvtx-z", "tag": "chip", "seed": 301, "injections": [
        inject("chip_z", "MVTX", 2, [10], [3], "z", offset_mm=-0.012,
               expected="B")]},
    {"id": "chip-mvtx-rphi", "tag": "chip", "seed": 302, "injections": [
        inject("chip_rphi", "MVTX", 0, [5], [0], "rphi", offset_mm=0.009,
               expected="B")]},
    {"id": "sensor-intt", "tag": "chip", "seed": 303, "injections": [
        inject("sensor_rphi", "INTT", 4, [6], [1], "rphi", offset_mm=0.040,
               expected="B")]},
    {"id": "two-adjacent-chips", "tag": "chip", "seed": 304, "injections": [
        inject("two_chips_rphi", "MVTX", 0, [3], [4, 5], "rphi",
               offset_mm=0.010, expected="B")]},
    {"id": "width-chip", "tag": "width", "seed": 401, "injections": [
        inject("chip_width", "MVTX", 0, [2], [5], sigma_scale=1.4,
               expected="C")]},
    {"id": "width-stave", "tag": "width", "seed": 402, "injections": [
        inject("stave_width", "MVTX", 1, [9], coord="rphi", sigma_scale=1.3,
               expected="C")]},
    {"id": "mean-width-chip", "tag": "mean+width", "seed": 403,
     "injections": [
         inject("chip_mean_width", "MVTX", 2, [3], [4], "rphi",
                offset_mm=0.010, sigma_scale=1.4, expected="D")]},
    {"id": "missing-ladder", "tag": "nc", "seed": 501,
     "injections": [MISSING_LADDER]},
    {"id": "sub-threshold-stave", "tag": "distractor", "seed": 601,
     "injections": [
         inject("sub_threshold_stave", "MVTX", 1, [2], coord="rphi",
                offset_mm=0.004, expected=None)]},
    {"id": "low-stats-width", "tag": "distractor", "seed": 602,
     "injections": [LOW_STATS_WIDTH]},
    {"id": "mixed-1", "tag": "mixed", "seed": 701, "injections": [
        inject("stave_rphi", "MVTX", 1, [4], coord="rphi", offset_mm=0.008,
               expected="A"),
        inject("chip_width", "MVTX", 0, [2], [5], sigma_scale=1.4,
               expected="C"),
        inject("chip_z", "MVTX", 2, [10], [3], "z", offset_mm=-0.012,
               expected="B"),
        inject("sub_threshold_chip", "MVTX", 2, [7], [0], "rphi",
               offset_mm=0.003, expected=None),
        inject("sensor_rphi", "INTT", 4, [6], [1], "rphi", offset_mm=0.040,
               expected="B"),
        LOW_STATS_WIDTH,
        LOW_STATS_LADDER,
        MISSING_LADDER]},
    {"id": "mixed-2", "tag": "mixed", "seed": 702, "injections": [
        inject("chip_width", "MVTX", 0, [2], [5], sigma_scale=1.4,
               expected="C"),
        inject("chip_z", "MVTX", 2, [10], [3], "z", offset_mm=-0.012,
               expected="B"),
        LOW_STATS_LADDER,
        inject("half_layer_z", "MVTX", 2, list(range(10)), coord="z",
               offset_mm=0.006, expected="A")]},
]
