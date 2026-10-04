# AI triage: Iter1 vs Iter0

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
| comparison | Iter1 | ntuple_list2.txt | |

Source: flags_Iter0_vs_Iter1.csv (sha256 d4d3caffb03b), summary_Iter0_vs_Iter1.json (sha256 b356285a1692). Synthetic data from `make_synthetic_fit_tables.py`, seed 20261001.

## Criteria

- Width: |(sigma2 - sigma1)/sigma1| > 0.2
- Mean: |mu2 - mu1| / sqrt(dmu1^2 + dmu2^2) > 1.96 and |mu2 - mu1| > minimum shift (MVTX:rphi 5 um, MVTX:z 5 um, INTT:rphi 20 um, INTT:z 1000 um)
- Flagged if width OR mean fires.

Flagged 13 of 1296 comparable entries (11 mean, 2 width, 16 not comparable).

## AI triage

### Overview

Iter1 differs from Iter0 in four localised places: one MVTX stave moved
coherently in r-phi, one MVTX chip moved in z, one INTT sensor moved in
r-phi, and one MVTX chip became wider in both coordinates. Everything else is
stable: apart from one entry discussed below, no unflagged comparable entry
has a mean shift with z > 3.5, and no unflagged entry approaches the minimum
shift (largest: MVTX 0.8 um, INTT r-phi 1.4 um, INTT z 0.27 mm). Two INTT
ladders cannot be compared: one has almost no data in either input, one is
absent from Iter1.

### Grouped findings

| Group | Entries | Evidence |
|---|---|---|
| A. Stave-wide mean shift | MVTX L1 stave 4, chips 0–8, r-phi (9) | All 9 chips shift +7.9 to +8.5 um (median +8.17 um, chip-to-chip spread 0.17 um, all positive), z = 41–48. Widths unchanged (\|sigma rel\| < 3%). Local z of the same stave unchanged. Consistent with a rigid displacement of the stave in r-phi. |
| B. Isolated chip mean shift | MVTX L2 stave 10 chip 3, z (1) | −12.0 um, z = 60; other 8 chips of the stave unchanged; width +3.7% (not significant). |
| B. Isolated sensor mean shift | INTT L4 ladder 6 sensor 1, r-phi (1) | +40.3 um, z = 90 (about 1.6× the 24 um width); other 3 sensors on the ladder unchanged (ladder median +0.2 um); width unchanged. |
| C. Width-only change | MVTX L0 stave 2 chip 5, r-phi and z (2) | sigma 7.3 → 10.2 um (+40%) in r-phi and 7.4 → 10.4 um (+40%) in z, significance ≈ 15; mean unchanged (z < 1.6). Other chips of the stave unchanged. |
| D. Mean and width | none | — |
| E. Not comparable | INTT L3 ladder 3 (8 rows); INTT L5 ladder 9 (8 rows) | L3/3: low_stats in both inputs (all 4 sensors, both coords). L5/9: fit ok in Iter0, missing in Iter1. |

### Inspect first

1. **MVTX L1 stave 4 (r-phi, +8.2 um, all chips).** The largest coherent
   effect, and typical of a stave-level alignment difference between the
   two configurations. Check whether the stave's alignment constants differ
   between Iter0 and Iter1. Also check for a matching residual pattern in the
   neighbouring staves and in the INTT behind this stave, which a rotated
   half-barrel or a wrong layer radius would produce. None is seen here.
2. **INTT L4 ladder 6 sensor 1 (r-phi, +40 um).** A single-sensor shift of
   more than one resolution width will bias the INTT contribution to tracks
   through that sensor. Check that sensor's alignment entry and its mapping
   (a sensor/ladder mis-assignment would also appear as an isolated offset).
3. **MVTX L2 stave 10 chip 3 (z, −12 um).** Isolated chip-level z
   displacement; check the chip-level alignment constant.
4. **MVTX L0 stave 2 chip 5 (width +40% in both coordinates, mean
   unchanged).** A pure translation would not broaden the distribution. An
   in-plane rotation or tilt of the chip, or a change in cluster
   reconstruction for that chip (masking, threshold, cluster size), would.
   Look at residual vs local position on the chip and at the cluster-size
   distribution.
5. **INTT L5 ladder 9 absent in Iter1.** Determine whether the ladder was
   off, masked, or dropped in reconstruction for Iter1.

### Likely statistical or benign

- **MVTX L2 stave 7 chip 0, r-phi: +3.7 um, z = 20, not flagged.**
  Statistically clear but below the 5 um minimum shift; widths unchanged. It
  is the only unflagged entry with z > 5. Worth a look if sub-5 um
  stability matters, but it is not a flag.
- **MVTX L0 stave 9 chip 8, r-phi: only 40 entries in each input.** sigma
  relative change −1.3% ± 18%, so changes below roughly 35% cannot be
  detected here. Treat "unchanged" as "not measurable".
- **INTT L3 ladder 3: 5 entries per sensor in both inputs.** Appears
  effectively absent in both configurations (dead or masked); it is not a
  change between them.
- INTT z entries (largest unflagged shift 0.27 mm, z = 3.0) are far below
  the 1 mm minimum shift. INTT z fits are only indicative anyway.

### Suggested follow-up checks

- Fill in the configuration table above, in particular the
  alignment/geometry tag of each label. Every flagged change here looks like
  geometry, apart from the broadened chip.
- For each flagged entry, look at the overlaid residual pages from
  `plot_fits_overlaid_stavechip.C` run with
  `"ntuple_list1.txt:Iter0,ntuple_list2.txt:Iter1"`.
- For MVTX L0 stave 2 chip 5: plot residual vs local column/row to
  distinguish rotation from a reconstruction change.
- Check that the track selection and run conditions are the same for both
  labels, since they affect the widths.
