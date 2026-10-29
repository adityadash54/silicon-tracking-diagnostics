# runs/

One folder per comparison, created by `stdiag.compare_runs`: comparing
`residual_fits_<a>.csv` with `residual_fits_<b>.csv` (the first is the
reference) writes `runs/<a>_vs_<b>/`. Every later step writes into the same
folder:

| Step | Files in `runs/<a>_vs_<b>/` |
|---|---|
| `stdiag.compare_runs` | `flags_*.csv`, `summary_*.json`, `report_*.md` |
| `stdiag.triage_agent` | `triage_report_*.md`, `findings_*.json` |
| `stdiag.review` | `review_*`, `dialogue_*`, expert answers and checks |

**Running the same comparison again deletes `runs/<a>_vs_<b>/` and writes it
afresh**, so the triage and review files of the earlier run are removed too,
because they described the old flags. Copy anything you want to keep first,
and keep `labels.csv` outside this folder (for example in the repository root,
which is the default `review ask` reads).

The folder name comes from the file names, the file names inside from the
`label` column of each table (the macro keeps them the same). Set
`STDIAG_RUNS_DIR` to put the folders elsewhere; `--out-dir DIR` writes a
comparison to `DIR` instead, without deleting anything.

Nothing in this folder except this README is committed (`.gitignore`).
