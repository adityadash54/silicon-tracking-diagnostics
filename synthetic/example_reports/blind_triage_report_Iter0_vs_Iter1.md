# AI triage: Iter1 vs Iter0

Generated 2026-10-02T00:27:13+00:00 by triage_agent.py with claude-opus-5-5 via Claude Code CLI. The interpretation below is AI-generated from the deterministic flags of compare_runs.py; verify it against the residual plots before acting.

## Inputs and detector configuration

Record the detector/reconstruction configuration of each label below.

| Role | Label | List file | Detector configuration (fill in) |
|---|---|---|---|
| reference | Iter0 | ntuple_list1.txt | |
| comparison | Iter1 | ntuple_list2.txt | |

Source: flags_Iter0_vs_Iter1.csv (sha256 d4d3caffb03b), summary_Iter0_vs_Iter1.json (sha256 d31ba9627f93).

## Criteria

- Width: |(sigma2 - sigma1)/sigma1| > 0.2
- Mean: |mu2 - mu1| / sqrt(dmu1^2 + dmu2^2) > 1.96 and |mu2 - mu1| > minimum shift (MVTX:rphi 5 um, MVTX:z 5 um, INTT:rphi 20 um, INTT:z 1000 um)
- Flagged if width OR mean fires.

Flagged 13 of 1296 comparable entries (11 mean, 2 width, 16 not comparable).

## AI triage

### Overview
This report compares **Iter1** against the reference **Iter0**, using the outputs of `compare_runs.py`. The CSV files are `residual_fits_Iter0.csv` and `residual_fits_Iter1.csv`, and their sha256 hashes are recorded in the summary. The flags below are the tool's own; none were added or removed.

- **Rows:** 1312 in total. 1296 are comparable and 16 are not.
- **Flags:** 13 entries are flagged. 11 are mean shifts, 2 are width changes, and none have both.
- **Where the flags are:**
  - MVTX layer 1 r-phi: 9
  - MVTX layer 0: 1 in r-phi and 1 in z
  - MVTX layer 2 z: 1
  - INTT layer 4 r-phi: 1
  - Nothing is flagged in MVTX layer 1 z, MVTX layer 2 r-phi, INTT layers 3, 5 or 6, or any INTT z fit.
- **What the flags mean:** they come from only 4 objects:
  - one whole MVTX stave shifted in r-phi
  - one MVTX chip that got wider
  - one INTT sensor shifted in r-phi
  - one MVTX chip shifted in z
- **Not comparable:** the 16 entries are two whole INTT ladders.
  - **L3 ladder 3:** only 5 entries per sensor in both inputs (`low_stats`).
  - **L5 ladder 9:** fitted normally in Iter0 but `missing` in Iter1.
- **Statistics:** every flagged entry has a good fit in both inputs (`ok`) with about 2900–6000 entries. None of them is close to the statistics limit.
- **Separation:** the `separation` values match Δμ/√(σ₁²+σ₂²). I read them that way below, which is an inference, not something the tool documents.

I don't know what configuration lies behind either label, so this report says *what* changed, not *why*.

### Grouped findings

| Group | Entries | Evidence |
|---|---|---|
| **A. Coherent stave-wide mean shift** | MVTX L1 stave 4, chips 0–8, r-phi (9 flags) | • All 9 chips shift in the same direction (fraction positive = 1.0).<br>• Δμ ranges from +7.89 µm (chip 2) to +8.46 µm (chip 5). Median +8.17 µm, spread across chips 0.17 µm.<br>• mu_z = 40.7–48.0; separation = 0.75–0.90.<br>• No trend along the stave: chips 0, 4 and 8 read +8.24, +7.96 and +8.24 µm.<br>• Widths unchanged: σ_rel −2.8% to +2.0%, significance ≤ 1.54.<br>• The same stave in z is unchanged on every chip: \|Δμ\| ≤ 0.37 µm, significance ≤ 1.48.<br>• So the stave appears offset rigidly in r-phi only. |
| **B. Isolated chip/sensor mean shift** | INTT L4 ladder 6, sensor 1, r-phi | • Δμ = +40.3 µm (mu_z = 90.0, separation = 1.20). That is twice the 20 µm minimum shift and larger than the sensor's width.<br>• Width 23.6 → 24.0 µm, significance 1.28, so unchanged.<br>• The other sensors on the ladder are unchanged: −0.28, −0.70 and +0.67 µm.<br>• Sensor 1 in z: Δμ = −0.081 mm on a width of about 4.1 mm. Not flagged, and INTT z fits are indicative only. |
| **B. Isolated chip/sensor mean shift** | MVTX L2 stave 10, chip 3, z | • Δμ = −12.0 µm (mu_z = 60.4, separation = 1.13).<br>• Width 7.36 → 7.63 µm (+3.7%, significance 1.90). That is below ~2, so compatible with fluctuation.<br>• The same chip in r-phi is unchanged (Δμ = 0.0 µm).<br>• The other 8 chips of stave 10 in z are within −0.19 to +0.07 µm. |
| **C. Width-only change** | MVTX L0 stave 2, chip 5, r-phi and z (2 flags) | • r-phi width 7.29 → 10.18 µm (+40%, significance 14.96).<br>• z width 7.42 → 10.42 µm (+40%, significance 15.48).<br>• Means unchanged: −0.11 µm in r-phi, −0.36 µm in z.<br>• Entries 2969/2952 (r-phi) and 2901/3103 (z).<br>• Significance near 15 cannot be a statistical fluctuation.<br>• The other 8 chips of stave 2 have widths within ±3.6%, all with significance below 2. |
| **D. Mean and width together** | None | `flag_mean_and_width` = 0. |
| **E. Statistics limit / suspicious fits** | No flagged entries | All 13 flagged entries are `ok` in both inputs with about 2900–6000 entries. The only low-statistics cases are the not-comparable INTT L3 ladder 3 entries (row below). |
| **Not comparable** | INTT L3 ladder 3, sensors 0–3, r-phi and z (8 rows) | `low_stats` in both Iter0 and Iter1, with 5 entries each. The problem is in both inputs, so it is not a difference between them. |
| **Not comparable** | INTT L5 ladder 9, sensors 0–3, r-phi and z (8 rows) | • Iter0 fits are good: 5880–6136 entries; r-phi widths 24.2–26.4 µm; z widths 4.23–4.52 mm.<br>• Iter1 is `missing` for the whole ladder. |

**Patterns across layers and coordinates:**
- **MVTX:** all mean flags are confined to one coordinate per object. Stave 4 moved only in r-phi, and stave 10 chip 3 moved only in z.
- **Width:** the only width change (L0 stave 2 chip 5) affects both coordinates equally, which looks more like a resolution change on the chip than a geometric shift.
- **INTT:** the only flag is one sensor in r-phi. Both incomplete INTT ladders are whole ladders (all 4 sensors, both coordinates), not single sensors.

### Inspect first
1. **MVTX L1 stave 4, r-phi (all 9 chips, about +8.2 µm):** this is the largest group and the clearest alignment signal. The shift is uniform along the stave and appears only in r-phi, which fits a rigid stave-level r-phi offset or rotation about the beam axis. Whether it is an intended difference between the inputs or a misalignment depends on what differs between Iter0 and Iter1, which you have recorded.
2. **MVTX L0 stave 2, chip 5, r-phi and z (width +40%, significance about 15):** a single chip is broadened in both coordinates while its mean stays put and its neighbours are stable. This points to a local effect on the chip (hardware, calibration, cluster-shape or chip-level alignment) rather than statistics.
3. **INTT L5 ladder 9 (missing in Iter1):** a whole ladder that fitted normally in Iter0 is absent from Iter1. Coverage needs explaining before results that involve this ladder are compared.
4. **INTT L4 ladder 6, sensor 1, r-phi (+40.3 µm, separation 1.20):** the largest shift relative to resolution in the comparison, isolated to one sensor.
5. **MVTX L2 stave 10, chip 3, z (−12.0 µm, separation 1.13):** isolated chip shift in z only. Its width change (significance 1.90) is not significant.
6. **INTT L3 ladder 3 (5 entries per sensor in both inputs):** not a change between the inputs, but the ladder cannot be checked in either.

### Likely statistical or benign
- **Width changes alongside the mean flags:** all are compatible with fluctuation, as every significance is below ~2:
  - L1 stave 4: ≤ 1.54
  - INTT L4 ladder 6 sensor 1: 1.28
  - L2 stave 10 chip 3: 1.90
- **The mean flags themselves are not statistical.** With about 3000–6000 entries per fit, mu_z values of 40–90 are expected for these shift sizes, and the minimum-shift cut is what decides them:
  - L1 stave 4: about 8 µm against a 5 µm minimum
  - L2 stave 10 chip 3: 12 µm against 5 µm
  - INTT L4 ladder 6 sensor 1: 40 µm against 20 µm

  Whether these shifts are *benign* depends on what differs between the inputs. I can't judge that.
- **INTT L4 ladder 6 z:** Δμ ranges from −0.15 to +0.17 mm on widths of 4.1–5.1 mm, all unflagged. The fits are indicative only, and nothing there suggests a change.
- **Unflagged entries with width significance just above 2** in the staves examined:
  - INTT L4 ladder 6 sensor 3 r-phi: −2.6%, significance 2.03
  - MVTX L2 stave 10 chip 6 r-phi: +4.6%, significance 2.36

  Both relative changes are small. The flags are final and they remain unflagged; I mention them only for completeness.
- **INTT L3 ladder 3:** the low statistics are the same in both inputs (5 entries), so this does not separate Iter0 from Iter1.

### Suggested follow-up checks
- **L1 stave 4:**
  - Overlay the Iter0 and Iter1 r-phi residual histograms for chips 0–8.
  - Pull `get_stave_overview` without the flags-only filter for all L1 staves, especially staves 3 and 5. This shows whether stave 4 stands alone or neighbouring staves have smaller shifts in the same direction below the 5 µm cut.
  - Compare the stave-level alignment parameters used for stave 4 in the two inputs, against your configuration notes.
- **L0 stave 2, chip 5:**
  - Overlay the residual histograms in both coordinates and look for tails, a second peak, or a fit range that misses part of the distribution.
  - Compare hit maps, cluster-size distributions, masked or noisy pixel lists and chip-level alignment parameters for this chip between the inputs.
  - If either input spans several runs, check whether the broadening is present in all of them.
- **INTT L5 ladder 9:**
  - Check whether any hits or clusters from this ladder are in the Iter1 ntuples (`ntuple_list2.txt`).
  - Check whether the ladder was removed by a selection, a geometry or readout mapping, or a gap in file coverage.
- **INTT L4 ladder 6, sensor 1:** overlay the r-phi histograms and compare sensor-level alignment parameters. For z, look at the raw distribution rather than the Gaussian fit.
- **L2 stave 10, chip 3:** overlay the z histograms and check the chip-level z alignment parameter in both inputs.
- **INTT L3 ladder 3:** check the hit map and cluster counts in both inputs to see whether there is any usable data.
- **Provenance:** confirm the two CSV hashes match the intended fit outputs, and record which configuration each label stands for before drawing conclusions.
