# inputs/

Put the fit tables you want to compare here. They are named
`residual_fits_<name>.csv`, as `macros/plot_fits_overlaid_stavechip.C` writes
them; give the macro `inputs` as its CSV output folder to write them here
directly.

```bash
python3 -m stdiag.compare_runs inputs/residual_fits_Iter0.csv inputs/residual_fits_Iter1.csv
```

This compares `Iter1` with the reference `Iter0` (the first file) and writes
the results to `runs/Iter0_vs_Iter1/`; see [`../runs/README.md`](../runs/README.md).
The exact steps, including triage and review, are in
[Compare your own CSV files](../README.md#compare-your-own-csv-files).

## Example tables

`residual_fits_example_iter0.csv` and `residual_fits_example_iter1.csv` are a
synthetic example pair, so you can try the steps straight away:

```bash
python3 -m stdiag.compare_runs inputs/residual_fits_example_iter0.csv inputs/residual_fits_example_iter1.csv
```

They are the stave/chip demo (`synthetic/stavechip_demo/`): one MVTX stave and
one INTT ladder with known shifts and a vertex offset. The expected result is
`10 flagged of 57 comparable (3 not comparable)` in
`runs/example_iter0_vs_example_iter1/`; the demo README explains every flag.

## What is committed

Only this README and the two example tables. Every other file you put here is
ignored by git (`.gitignore`), so real data stays on your machine. Do not name
your own files `residual_fits_example_*.csv`: those two names are tracked.
