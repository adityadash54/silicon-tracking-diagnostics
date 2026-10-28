# Reference output of the synthetic pipeline

One committed set of the CSV tables that `synthetic/run_full_pipeline.sh`
produces, so you can check that your own run gives the same answer. The
synthetic ROOT files themselves (about 20 MB each) are not committed; the
script regenerates them in a few seconds.

## Files

| File | Written by | Content |
|---|---|---|
| `injections.csv` | `synthetic.make_synthetic_fit_tables` | The injected truth: nine changes, which labels they apply to |
| `residual_fits_Iter{0,1,2}.csv` | `macros/plot_fits_overlaid_stavechip.C` | Per-chip, whole-stave (`chip = −1`) and VERTEX fits, 1550 rows per label |
| `vertex_phi_fit_Iter{0,1,2}.csv` | `macros/plot_fits_overlaid_stavechip.C` | A·sin(φ − φ0) + c fit to ⟨−DCA_xy⟩ vs track φ |

The ROOT files came from `synthetic/make_synthetic_ntp.C` with its defaults
(seed 20261001, `entriesScale` 1); the fit macro ran in CSV-only mode.

## Expected results

| Comparison | Rows | Comparable | Not comparable | Flagged (chip / stave / VERTEX) | Truth check |
|---|---|---|---|---|---|
| Iter1 vs Iter0 | 1550 | 1531 | 19 | 17 (14 / 3 / 0) | PASS, 1550/1550 |
| Iter2 vs Iter0 | 1550 | 1541 | 9 | 105 (94 / 11 / 0) | PASS, 1550/1550 |

The vertex fit gives A ≈ 30 µm and φ0 ≈ 0 in every label (the generator puts
the same +30 µm x offset into all three), so no VERTEX row is flagged.

`python -m synthetic.compare_to_reference synthetic/pipeline_output` (step 6
of the script) checks a run against these tables: entry counts and fit
statuses must match exactly, fitted values within a relative 10⁻⁴.

## Provenance

Made on 2026-10-27 with ROOT 6.40/04, Python 3.14.6, NumPy 2.4.6 and pandas
3.0.3 on macOS 26.6 (arm64). Two independent runs gave byte-identical
tables, and the truth check passed for seeds 1–8 as well.

SHA-256:

```
6592a6a242d86426f0c4bad889f352cdc5b164a5699c7d1d6f08a90aa4e65edd  injections.csv
220c154142b56493f0634b2868576668c2178153eeaa4b24d2d8a051241e0f9e  residual_fits_Iter0.csv
6ea16b4571a6cfda0b93b9adf3d5cce743eee10900fca15ddcedfec03ba92b20  residual_fits_Iter1.csv
e9f92782b3a5a3f942896e56046741433596d5ce5209d7c67dbdb91b4ad22add  residual_fits_Iter2.csv
b006e444344159647eb6815abc6c66733235233e846aff7491b566180e267307  vertex_phi_fit_Iter0.csv
c1e85da3841cc62928ded2824d4f2f42f0be06c73c32459926ac94498a178d77  vertex_phi_fit_Iter1.csv
2df851f8eb404534ec23a6e723cda16337303d96063f5d5a628961c667d6cc8f  vertex_phi_fit_Iter2.csv
```

A different checksum on another platform or ROOT version is not by itself a
problem (fits can differ in the last digits); `compare_to_reference` decides.

## What is synthetic here

Everything. The geometry (MVTX 12/16/20 staves × 9 chips; INTT 12/12/16/16
ladders × 4 sensors with 20/16/16/20 mm strips) and the nominal widths
(approximately pitch/√12: ALPIDE 26.88 × 29.24 µm pixels, INTT 78 µm strips)
come from public sPHENIX specifications; offsets, statistics, the vertex model
and seeds are invented. No real-data values are used.
