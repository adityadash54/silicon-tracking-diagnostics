# AI triage: Iter2 vs Iter0

Generated 2026-10-02T00:18:33Z in an interactive Claude Code session (Claude
Opus 5.5), **not** by `triage_agent.py`. It follows the same instructions as
`triage_agent.py` and uses the same read-only tool functions over the layer-2
tables, but the session that wrote it also designed the synthetic injections,
so it is **not a blind test** of AI triage. Verify against the residual plots
before acting.

## Inputs and detector configuration

Record the detector/reconstruction configuration of each label below.

| Role | Label | List file | Detector configuration (fill in) |
|---|---|---|---|
| reference | Iter0 | ntuple_list1.txt | |
| comparison | Iter2 | ntuple_list3.txt | |

Source: flags_Iter0_vs_Iter2.csv (sha256 e68835e63638), summary_Iter0_vs_Iter2.json (sha256 9ecb7453f038). Synthetic data from `make_synthetic_fit_tables.py`, seed 20261001.

## Criteria

- Width: |(sigma2 - sigma1)/sigma1| > 0.2
- Mean: |mu2 - mu1| / sqrt(dmu1^2 + dmu2^2) > 1.96 and |mu2 - mu1| > minimum shift (MVTX:rphi 5 um, MVTX:z 5 um, INTT:rphi 20 um, INTT:z 1000 um)
- Flagged if width OR mean fires.

Flagged 93 of 1304 comparable entries (91 mean, 2 width, 8 not comparable).

## AI triage

### Overview

The dominant change is a coherent +6 um local-z shift of MVTX layer 2
staves 0–9, every chip of all 10 staves, while staves 10–19 of the same layer
are unchanged. Two single-chip effects are also present: MVTX L0 stave 2
chip 5 is 40% wider, and MVTX L2 stave 10 chip 3 is shifted −12 um in z.
They match the same two entries in the Iter1-vs-Iter0 comparison, so they
persist across both configurations. Nothing in INTT changed. The only
non-comparable entries are INTT L3 ladder 3, which has almost no data in
either input. No unflagged comparable entry has a mean shift with z > 3.6.

### Grouped findings

| Group | Entries | Evidence |
|---|---|---|
| A. Coherent shift of half a layer | MVTX L2 staves 0–9, all chips, z (90) | Per-stave median shifts +5.88 to +6.14 um, chip-to-chip spread 0.1–0.3 um, 100% positive, z = 25–32; staves 10–19 median 0.0 um (one flag, below). r-phi of staves 0–9 unchanged (0 flags). Widths unchanged. Layers 0 and 1 show no shift. |
| B. Isolated chip mean shift | MVTX L2 stave 10 chip 3, z (1) | −12.0 um, z = 61, width unchanged; same entry and size as in Iter1 vs Iter0. |
| C. Width-only change | MVTX L0 stave 2 chip 5, r-phi and z (2) | sigma +41% (r-phi) and +40% (z), significance ≈ 15, mean unchanged; same as in Iter1 vs Iter0. |
| D. Mean and width | none | — |
| E. Not comparable | INTT L3 ladder 3 (8 rows) | low_stats in both inputs. |

### Inspect first

1. **MVTX layer 2, staves 0–9, local z +6 um.** A rigid z translation of
   half of one layer. If staves are numbered sequentially in azimuth, staves
   0–9 are one azimuthal half of layer 2, which points to a layer-2
   half-barrel z alignment parameter rather than individual staves. The inner
   layers of the same half did not move, so it is not a rigid motion of a
   whole half-barrel. Compare the layer-2 half-barrel z constants between the
   Iter0 and Iter2 configurations, and check the stave numbering convention.
2. **MVTX L0 stave 2 chip 5 (width +40%).** Persistent across both
   comparisons, so it is not specific to one configuration. A real chip-level
   effect: rotation/tilt, or a reconstruction/masking change. See the
   Iter1-vs-Iter0 report for checks.
3. **MVTX L2 stave 10 chip 3 (z, −12 um).** Persistent across both
   comparisons; chip-level z alignment.

### Likely statistical or benign

- **MVTX L0 stave 9 chip 8, r-phi: 40 entries per input.** sigma relative
  change +11% ± 17%; changes below roughly 35% cannot be detected.
- **INTT L3 ladder 3: low statistics in both inputs**, as in Iter1 vs Iter0.
- Largest unflagged shifts: MVTX 1.0 um, INTT r-phi 1.6 um, INTT z 0.24 mm,
  all well below the minimum shifts.

### Compared with Iter1 vs Iter0

The Iter1-only changes are absent here: the MVTX L1 stave 4 r-phi shift, the
INTT L4 ladder 6 sensor 1 shift, and the missing INTT L5 ladder 9. Each
of those entries has returned to its Iter0 value in Iter2.

### Suggested follow-up checks

- Fill in the configuration table, in particular the alignment/geometry tag
  of Iter2 and what was changed relative to Iter0 and Iter1.
- Run `plot_fits_overlaid_stavechip.C` with
  `"ntuple_list1.txt:Iter0,ntuple_list2.txt:Iter1,ntuple_list3.txt:Iter2"`
  and look at the layer-2 pages: the z panels of staves 0–9 should show the
  Iter2 curve offset by +6 um.
- Plot the per-stave median z shift against stave number for layer 2. A
  step at stave 10 confirms a half-layer effect; a smooth variation would
  point instead to a rotation or a radius/z-scale problem.
