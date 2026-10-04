# AI triage: Iter2 vs Iter0

Generated 2026-10-02T00:28:27+00:00 by triage_agent.py with claude-opus-5-5 via Claude Code CLI. The interpretation below is AI-generated from the deterministic flags of compare_runs.py; verify it against the residual plots before acting.

## Inputs and detector configuration

Record the detector/reconstruction configuration of each label below.

| Role | Label | List file | Detector configuration (fill in) |
|---|---|---|---|
| reference | Iter0 | ntuple_list1.txt | |
| comparison | Iter2 | ntuple_list3.txt | |

Source: flags_Iter0_vs_Iter2.csv (sha256 e68835e63638), summary_Iter0_vs_Iter2.json (sha256 30f7af128fbe).

## Criteria

- Width: |(sigma2 - sigma1)/sigma1| > 0.2
- Mean: |mu2 - mu1| / sqrt(dmu1^2 + dmu2^2) > 1.96 and |mu2 - mu1| > minimum shift (MVTX:rphi 5 um, MVTX:z 5 um, INTT:rphi 20 um, INTT:z 1000 um)
- Flagged if width OR mean fires.

Flagged 93 of 1304 comparable entries (91 mean, 2 width, 8 not comparable).

## AI triage

Iter2 differs from Iter0 in three ways:

* **Coherent shift:** every chip on MVTX layer 2 staves 0–9 moved about +6 µm in local z.
* **Isolated shift:** one MVTX chip (layer 2, stave 10, chip 3) moved −12 µm in z.
* **Broadening:** one MVTX chip (layer 0, stave 2, chip 5) became about 40% wider in both coordinates.

INTT has no flags. One INTT ladder (layer 3, ladder 3) is near-empty in both inputs.

### Overview

- **Inputs:** reference `Iter0` (`ntuple_list1.txt`) and comparison `Iter2` (`ntuple_list3.txt`).
- **Counts:** 1312 rows, of which 1304 are comparable and 8 are not comparable.
- **Flags:** 93 in total.
  - 91 are mean-only.
  - 2 are width-only.
  - None flag mean and width together.
- **Where the flags are:** all 93 are in MVTX.
  - 91 are in layer 2, local z.
  - 2 are in layer 0, on one chip, in r-phi and z.
- **No flags:**
  - MVTX layer 1 has none.
  - MVTX layer 2 r-phi has none.
  - INTT layers 3–6 have none in either coordinate.
- **Sign convention:** I read Δμ as `Iter2` minus `Iter0` (the reference is the first table). All flagged fits have status `ok` in both inputs, with about 2800–3250 entries each.

**Main pattern: half of MVTX layer 2 moved in z.** Layer 2 has 180 z rows, which is 20 staves × 9 chips.
- **Staves 0–9:** all 90 chips are mean-flagged in z.
  - Shifts run from +5.6 µm (stave 1, chip 6) to +6.4 µm (stave 8, chip 8).
  - Stave medians are +5.88 to +6.14 µm, and every shift is positive.
  - The spread within each stave is 0.11–0.27 µm. That is about the size of the statistical error on each Δμ: a 6 µm shift at z ≈ 28 gives roughly 0.2 µm per chip.
  - So the shift looks rigid and common to all ten staves.
- **R-phi on the same staves is unchanged.** |Δμ| ≤ 0.44 µm (largest is stave 8, chip 6), and no r-phi flags.
- **Stave 10 is unshifted** apart from chip 3. Its other chips are within ±0.26 µm in z, and its median is −0.07 µm.
- **Staves 11–19 have no flags.** The tool outputs I have do not give their actual z shifts.

### Grouped findings

| Group | Entries | Evidence |
|---|---|---|
| **A. Coherent stave-wide mean shift** | MVTX L2, staves 0–9, chips 0–8, z (90 entries) | <ul><li>Δμ = +5.6 to +6.4 µm, significance 24.8–32.5.</li><li>Shift/width ("separation") 0.46–0.60.</li><li>Stave medians +5.88 to +6.14 µm, std 0.11–0.27 µm, fraction positive 1.0 for all ten staves.</li><li>Widths essentially unchanged: \|σ_rel\| ≤ 5%.</li><li>Same staves unchanged in r-phi.</li><li>The shifts sit only 0.6–1.4 µm above the 5 µm minimum-shift threshold.</li></ul> |
| **B. Isolated chip mean shift** | MVTX L2 stave 10 chip 3, z | <ul><li>Δμ = **−12.0 µm**, significance 60.7, separation 1.15.</li><li>σ 7.36 → 7.43 µm (significance 0.47).</li><li>Entries 3046 / 3038.</li><li>Neighbours unchanged in z: chip 2 is +0.19 µm, chip 4 is −0.07 µm.</li><li>The same chip's r-phi is unchanged: Δμ = −0.009 µm.</li><li>Opposite sign and twice the size of the group A shift. It is the largest shift in the comparison.</li></ul> |
| **C. Width-only change** | MVTX L0 stave 2 chip 5, r-phi and z | <ul><li>r-phi: σ 7.29 → 10.26 µm (+41%), sigma_rel_significance **15.4**, Δμ = +0.085 µm.</li><li>z: σ 7.42 → 10.37 µm (+40%), sigma_rel_significance **15.2**, Δμ = +0.117 µm.</li><li>Entries 2969/3025 (r-phi) and 2901/3044 (z).</li><li>Both well above ~2, so not a statistical fluctuation.</li><li>The other eight chips on this stave are unchanged: \|σ_rel\| ≤ 4%, \|Δμ\| ≤ 0.28 µm.</li><li>The broadening is the same in both coordinates.</li></ul> |
| **D. Mean and width together** | None | `flag_mean_and_width` = 0. |
| **E. Near statistics limit / suspicious fits** | No flagged entries | <ul><li>All flagged fits have status `ok` with about 2800–3250 entries.</li><li>A single Gaussian may still hide tail changes, especially for the broadened chip in group C.</li></ul> |
| **Not comparable** | INTT L3 ladder 3, sensors 0–3, r-phi and z (8 rows) | <ul><li>`low_stats` in **both** `Iter0` and `Iter2`, with 5 entries each.</li><li>The whole ladder is effectively empty in both inputs, so this is not a difference between them.</li></ul> |

### Inspect first

1. **MVTX L2 staves 0–9, z (group A).**
   - Ninety chips move together by about +6 µm. The move is rigid along each stave and the same across ten consecutive staves.
   - Layers 0 and 1, the r-phi coordinate, and L2 stave 10 show no matching shift.
   - This points to a common translation of that group of staves rather than ten independent stave misalignments.
   - If staves 0–9 form one mechanical unit, such as a half-layer or half-barrel, this would fit. I have not verified that mapping.
2. **MVTX L0 stave 2 chip 5, r-phi and z (group C).**
   - About 40% broadening at more than 15σ in both coordinates, with no mean shift and no effect on neighbouring chips.
   - Possible causes are a change in hit/cluster quality on this chip, or a misalignment that a single offset cannot describe, such as a rotation or tilt across the chip.
3. **MVTX L2 stave 10 chip 3, z (group B).**
   - An isolated −12.0 µm shift with an unchanged width and unchanged neighbours, which looks like a chip-level effect.
4. **INTT L3 ladder 3, sensors 0–3.**
   - Effectively no residuals in either input, so the ladder cannot be monitored. This is a coverage gap rather than a change.

### Likely statistical or benign

- **INTT:** no flags in any layer or coordinate. INTT z fits are indicative only in any case.
- **Small width changes on group A chips.** Some flagged-in-mean chips have width changes with significance just above 2, but they are all under 5% and below the 20% width threshold:
  - L2 S0 C4 z: −4.9%, significance 2.65
  - L2 S6 C4 z: −4.9%, 2.79
  - L2 S6 C7 z: −4.3%, 2.34
  - L2 S5 C0 z: +4.7%, 2.32
- **Unflagged rows with width significance just above 2:**
  - L2 S0 C8 r-phi: 2.56
  - L2 S1 C3 r-phi: 2.36
  - L2 S10 C6 r-phi: 2.27
  - L0 S2 C7 r-phi: 2.06
- **Why these look like chance.** About 8 of roughly 230 inspected rows exceed 2, which is about what a two-sided 1.96 cut would give by chance. All are small (<5%).
- **Physical size of the group A shift.** It is significant but small: about 0.5 of the residual width, and only just above the 5 µm cut. It is still not a fluctuation, because it is so uniform across 90 chips.

### Suggested follow-up checks

- **Extent of the layer 2 z shift**
  - Run `get_stave_rows` for L2 staves 11–19 in z. Unflagged does not mean zero, and a sub-threshold shift of a few µm there would change the interpretation from a half-layer pattern to a layer-wide one.
  - Check the stave-to-half-barrel and stave-to-azimuth mapping for L2 staves 0–9.
  - Check L0 and L1 staves at the same azimuth for sub-threshold z shifts in the same direction.
- **Inputs behind the two labels**
  - Compare the geometry and alignment constants that were actually used to produce `Iter0` and `Iter2` for L2 staves 0–9 and for L2 S10 C3.
  - Note the configurations in your own records. I have not inferred what the labels correspond to.
- **L0 S2 C5 broadening**
  - Overlay the residual histograms for both inputs to see whether the core broadened or the tails grew.
  - Plot r-phi residual against local z, and z residual against local x, to look for a rotation or tilt signature.
  - Compare cluster size, hit maps, and noisy/masked pixel lists for this chip between the two inputs.
- **L2 S10 C3**
  - Overlay the z residual histograms for both inputs.
  - Check the chip-level constant for this chip in each input.
  - Check whether the shift depends on track angle or on the side of the chip.
- **INTT L3 ladder 3**
  - Check hit maps and ladder status records for both inputs to see whether the ladder was excluded or inactive.
  - Confirm whether the low entries come from the detector itself or from track selection.
- **Fit quality**
  - Spot-check a few group A chips for fit quality, for example L2 S1 C6 (+5.6 µm) and L2 S8 C8 (+6.4 µm), to confirm that the Gaussian means reflect the distribution cores.
