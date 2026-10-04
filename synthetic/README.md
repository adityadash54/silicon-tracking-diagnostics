# Synthetic test

End-to-end test with known injected changes. Synthetic per-chip fit tables
(standing in for `macros/fit_residuals_to_table.C`) are run through the real
comparison (`stdiag.compare_runs`) and triage (`stdiag.triage_agent`), and
the flags are checked against the injected truth. For the framework itself,
see [`../README.md`](../README.md).

## What this test does

`make_synthetic_fit_tables.py` replaces the ROOT fit step. It writes fit tables for
the full geometry (MVTX 48 staves × 9 chips, INTT 56 ladders × 4 sensors,
two coordinates, 1312 rows per label) for three labels:

| Label | List file (nominal) | Synthetic "configuration" (record in the reports) |
|---|---|---|
| Iter0 | ntuple_list1.txt | Reference: no injected change |
| Iter1 | ntuple_list2.txt | Single-stave, single-chip and sensor changes; one INTT ladder missing |
| Iter2 | ntuple_list3.txt | Half of MVTX layer 2 shifted in z; chip changes carried over |

Model per chip and coordinate: a baseline chip offset (sigma 0.25 × nominal
width) and width spread (±10%) shared by all labels, so they cancel in the
comparison; N ~ Poisson(3000) for MVTX and Poisson(6000) for INTT; nominal
widths MVTX 7 um (r-phi) / 8 um (z), INTT 25 um (r-phi) / 4.6 mm (z).
Fitted values = true values + Gaussian noise with dmu = sigma/sqrt(0.95 N)
and dsigma = sigma/sqrt(2 × 0.95 N).

### Injected changes (relative to Iter0)

| Name | In | Where | Change | Expected |
|---|---|---|---|---|
| `stave_shift_rphi` | Iter1 | MVTX L1 stave 4, all 9 chips, r-phi | mean +8 um | 9 mean flags |
| `chip_broadened` | Iter1, Iter2 | MVTX L0 stave 2 chip 5, both coords | width × 1.40 | 2 width flags |
| `chip_shift_z` | Iter1, Iter2 | MVTX L2 stave 10 chip 3, z | mean −12 um | 1 mean flag |
| `sub_threshold_shift` | Iter1 | MVTX L2 stave 7 chip 0, r-phi | mean +3 um | significant but below 5 um: **not** flagged |
| `intt_sensor_shift` | Iter1 | INTT L4 ladder 6 sensor 1, r-phi | mean +40 um | 1 mean flag |
| `low_stats_width` | Iter1 | MVTX L0 stave 9 chip 8, r-phi, 40 entries in every label | width × 1.30 | statistically limited: either |
| `low_stats_ladder` | all | INTT L3 ladder 3, 5 entries per sensor | none | 8 rows not comparable |
| `missing_ladder` | Iter1 | INTT L5 ladder 9 | ladder absent | 8 rows not comparable |
| `half_layer_shift_z` | Iter2 | MVTX L2 staves 0–9, all chips, z | mean +6 um | 90 mean flags |

The same table is written to `synthetic/output/injections.csv`.
`check_against_truth.py` derives the expected status of every row from these
injections and the thresholds in the summary JSON, then compares it with
what `compare_runs.py` produced.

## Results (seed 20261001)

| Comparison | Comparable | Flagged | Not comparable | Truth check |
|---|---|---|---|---|
| Iter1 vs Iter0 | 1296 | 13 (9 stave shift + 2 broad chip + 1 chip z + 1 INTT sensor) | 16 (8 low-stats ladder + 8 missing ladder) | PASS, 1312/1312 rows |
| Iter2 vs Iter0 | 1304 | 93 (90 half-layer z + 2 broad chip + 1 chip z) | 8 (low-stats ladder) | PASS, 1312/1312 rows |

No unchanged chip was flagged by chance. Seeds 1–20 also all pass.

Things the test shows:

- **The minimum-shift requirement matters.** The +3 um sub-threshold chip
  was measured at +3.7 um with z = 20 (an unusually large, roughly 4 sigma,
  noise fluctuation in this seed; over 40 seeds the measured shift averages
  3.01 ± 0.18 um). Statistically it is a clear change, but it is below the
  5 um minimum shift and is correctly not flagged.
- **The original separation metric would miss real shifts.** The 8 um
  stave shift has |dmu| / sqrt(sigma1² + sigma2²) = 0.75–0.90 and the 6 um
  half-layer z shift 0.46–0.60, far below 1.96; the fit-error test gives
  z = 41–48 and z = 25–32.
- **Width changes at low statistics are unreliable.** The 40-entry chip with
  a real +30% width change was *not* flagged in this seed (measured −1%, with
  an uncertainty of ±18%); it is flagged in 16 of 20 seeds. Conversely, an
  unchanged 40-entry chip would pass the 20% width test by chance about 22%
  of the time. Check the `sigma rel signif.` column before trusting a width
  flag.

## How to run

```bash
synthetic/run_test.sh                  # tables -> comparison -> truth check -> triage dry run
synthetic/run_test.sh --ai             # also runs the triage via the API
synthetic/run_test.sh --ai-claude-code # same, via the Claude Code CLI (`claude -p`)
```

`--ai` needs `pip install anthropic` and either `ANTHROPIC_API_KEY` or
`ant auth login`. `--ai-claude-code` needs only the `claude` CLI logged in
(your Claude Code login, no API key); it runs `claude -p` with no tools from
an empty temporary directory, so the triage cannot see this README or
`injections.csv` and the test stays blind. Both send the synthetic summary and
fit rows to Anthropic (synthetic data only). Use
`PYTHON=/path/to/python synthetic/run_test.sh` to pick an interpreter (needs pandas
and numpy).

## Output files (`synthetic/output/`)

| File | Content |
|---|---|
| `residual_fits_Iter{0,1,2}.csv` | Synthetic fit tables |
| `injections.csv` | Injected truth |
| `flags_Iter0_vs_Iter{1,2}.csv` | Per-row comparison and flags |
| `summary_Iter0_vs_Iter{1,2}.json` | Counts, thresholds, labels, checksums |
| `report_Iter0_vs_Iter{1,2}.md` | **Comparison report** (no AI) |
| `truth_check_Iter0_vs_Iter{1,2}.txt` | Expected vs observed status |
| `triage_dry_run_Iter0_vs_Iter{1,2}.txt` | What the triage would send |
| `triage_report_Iter0_vs_Iter{1,2}.md` | AI triage report (only with `--ai` or `--ai-claude-code`) |

`synthetic/output/` is deleted at the start of every run, so reports worth
keeping live in `synthetic/example_reports/`:

| File | Content |
|---|---|
| `example_reports/triage_report_Iter0_vs_Iter{1,2}.md` | Written by hand in the Claude Code session that built this test. That session also designed the injections, so these are **not** blind. |
| `example_reports/blind_triage_report_Iter0_vs_Iter{1,2}.md` | Blind reports from the first live `--ai-claude-code` run (2026-10-02), made before the notable-unflagged block and `--strict-mcp-config` were added. One stray line about claude.ai connectors was removed from the Iter1 report. |

## Not covered by this test

- The ROOT macro `macros/fit_residuals_to_table.C` (needs ROOT and real `ntp`
  files). The synthetic tables replace its output, so the iterative fit
  itself is untested.
- Non-Gaussian shapes: INTT z residuals are closer to a box than a Gaussian,
  and real distributions have tails; the synthetic fits are ideal.
- The triage API backend (`--ai`): only its dry run was executed here. The
  Claude Code backend (`--ai-claude-code`) was run live on 2026-10-02 and its
  blind reports found every flagged injection. That run's prompt held only
  flagged staves, so it could not see the +3 um sub-threshold chip or the
  40-entry chip; the prompt now also carries the full stave overview of each
  flagged layer and a notable-unflagged list that includes both, but this
  version has not yet been run live.
