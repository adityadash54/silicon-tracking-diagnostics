# Triage eval: proposed cases (awaiting sign-off)

Each case is a synthetic comparison (reference vs comparison, full MVTX/INTT
geometry, 1312 rows per label) built with the generator in `synthetic/`,
with the injections below applied to the comparison only. The triage sees
only the comparison outputs, never the injections. Each case runs twice
(2 repetitions), so 21 cases × 2 = 42 triage runs.

Expected group follows the triage prompt: **A** coherent stave/ladder-wide
mean shift, **B** isolated chip/sensor mean shift, **C** width-only change,
**D** mean and width together, **NC** not comparable (no A–D finding
expected).

| id | tag | Injection(s) in the comparison | Flagged rows | Expected |
|---|---|---|---|---|
| null-1 | null | none (seed 101) | 0 | no A–D finding |
| null-2 | null | none (seed 102) | 0 | no A–D finding |
| null-3 | null | none; INTT L3 ladder 3 has 5 entries per sensor in both | 0 | no A–D finding; NC noted |
| stave-mvtx-rphi | stave | MVTX L1 stave 4, all chips, r-φ +8 µm | 9 | A |
| stave-mvtx-z | stave | MVTX L0 stave 7, all chips, z −12 µm | 9 | A |
| stave-intt-rphi | stave | INTT L5 ladder 3, all sensors, r-φ +35 µm | 4 | A |
| half-layer-z | stave | MVTX L2 staves 0–9, all chips, z +6 µm | 90 | A (one finding, or one per stave all in A) |
| whole-layer-rphi | stave | MVTX L1 all 16 staves, r-φ +7 µm | 144 | A (stress test: output size) |
| opposite-staves | stave | MVTX L1 stave 4 r-φ +8 µm and stave 5 r-φ −8 µm | 18 | two separate A findings (not merged) |
| chip-mvtx-z | chip | MVTX L2 stave 10 chip 3, z −12 µm | 1 | B |
| chip-mvtx-rphi | chip | MVTX L0 stave 5 chip 0, r-φ +9 µm | 1 | B |
| sensor-intt | chip | INTT L4 ladder 6 sensor 1, r-φ +40 µm | 1 | B |
| two-adjacent-chips | chip | MVTX L0 stave 3 chips 4 and 5, r-φ +10 µm | 2 | B (hard: two of nine chips is not stave-wide) |
| width-chip | width | MVTX L0 stave 2 chip 5, both coords, σ × 1.4 | 2 | C |
| width-stave | width | MVTX L1 stave 9, all chips, r-φ σ × 1.3 | 9 | C |
| mean-width-chip | mean+width | MVTX L2 stave 3 chip 4, r-φ +10 µm and σ × 1.4 | 1 | D |
| missing-ladder | nc | INTT L5 ladder 9 absent from the comparison | 0 | no A–D finding; NC noted |
| sub-threshold-stave | distractor | MVTX L1 stave 2, all chips, r-φ +4 µm (below the 5 µm minimum) | 0 | no A–D finding |
| low-stats-width | distractor | MVTX L0 stave 9 chip 8 with 40 entries in both, r-φ σ × 1.3 | 0 or 1 | no penalty either way |
| mixed-1 | mixed | the synthetic test's Iter1 (stave, chip, sensor, width, sub-threshold, low-stats, missing ladder) | 13 | A, B, B, C |
| mixed-2 | mixed | the synthetic test's Iter2 (half layer, chip, width) | 93 | A, B, C |

## Proposed grading (code only, from `findings_*.json`)

- **pass** (headline): validation passed, every flag-producing injection
  matched by one finding with the expected group, no false findings, no
  merged injections.
- **recall**: fraction of flag-producing injections matched. An injection is
  matched when one finding holds at least 80% of its flagged rows and at
  least 80% of that finding's flagged rows come from it.
- **group accuracy**: fraction of matched injections with the expected group.
- **false findings**: findings in groups A–D whose rows are mostly not
  flagged by any injection (counts the null and distractor cases).
- **merged**: findings that hold most of two different injections.
- **validation**: the triage output check passed.

Recorded per run, not scored: wall-clock time, cost and tokens (requires one
small change: the triage's `claude -p` call reports its usage in JSON), and
whether the run hit an error or timeout.
