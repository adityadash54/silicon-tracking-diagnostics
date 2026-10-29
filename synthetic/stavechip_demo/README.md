# Stave/chip demo: every step by hand

A small, readable example: one MVTX stave and one INTT ladder with known
shifts, made by `make_synth.C`. It is small enough to check every flag by eye,
and it exercises the parts of the fit macro that the big synthetic test does
not stress: chips outside the plotted or histogram range, the INTT z box fit,
and the vertex residuals.

## The injected truth (Iter0 = reference, Iter1 = comparison)

| Entry | Change | Expected with the current macro |
|---|---|---|
| MVTX L0 stave 0 chip 3, r-φ | 0 → +10 µm | flagged |
| chip 5, r-φ | +300 µm → 0 (outside the ±50 µm plot, inside the ±0.5 mm histogram) | flagged |
| chip 6 | +30 µm in both | unchanged |
| chip 7 | 6 entries | not comparable (`low_stats`) |
| chip 8, r-φ | +800 µm → 0 (outside the histogram in Iter0) | not comparable (`out_of_range`) |
| INTT L3 ladder 0 sensor 2, z | 0 → +1.5 mm (strip boxes of 20/16/16/20 mm) | flagged |
| other sensors, both stave rows (`chip = −1`) | none | unchanged |
| TPC-like rows (layer 20) | — | ignored |
| Vertex offset (vertex − track origin) | (30, 0) → (20, 10) µm, so Δ(−DCA_xy) = −10 sin φ − 10 cos φ µm | the dca_xy φ bins where \|Δ\| > 10 µm are flagged; `chip = −1` and dca_z unchanged |
| `vertex_phi_fit` | | A = 30 µm, φ0 = 0 (Iter0); A = 22.4 µm, φ0 = 0.464 rad (Iter1) |

`check_demo.py` encodes this table.

## Files

| Path | Content |
|---|---|
| `make_synth.C` | Writes `synthIter0.root` and `synthIter1.root` (`ntp` + `track_ntp`) |
| `run_demo.sh` | Runs everything (needs ROOT), with the current macro (`after/`) and with the old fit settings (`before/`) |
| `check_demo.py` | Compares a flags table (and the vertex fits) with the truth |
| `reference/after/`, `reference/before/` | Committed fit tables from `run_demo.sh`, so the steps below need no ROOT |
| `output/` | Written by `run_demo.sh` and by the steps below; git-ignored |

## Option A: one command (needs ROOT)

```bash
synthetic/stavechip_demo/run_demo.sh
```

Expected: `after` gives `10 flagged of 57 comparable (3 not comparable)` and
`PASS`. `before` is reported as disagreeing with the truth in four entries,
which is what the old settings got wrong. The plots are in
`output/after/residual_fits_after.pdf` and `output/before/residual_fits_before.pdf`.

## Option B: step by step (no ROOT needed)

Run from the repository root. The commands have no trailing `#` comments, so
they paste into zsh as they are. `D` holds the inputs; `OUT` is git-ignored,
so the committed files are never changed. To use the tables you made with
`run_demo.sh` instead, set `D=$PWD/synthetic/stavechip_demo/output/after`.

### 0. Set up

```bash
export PYTHONPATH=$PWD
D=$PWD/synthetic/stavechip_demo/reference/after
OUT=$PWD/synthetic/stavechip_demo/output/manual
mkdir -p "$OUT"
echo "$D" "$OUT"
```

Both printed paths must end in `synthetic/stavechip_demo/...`.

### 1. Inspect the inputs

```bash
python3 -c "
import pandas as pd
for label in ('Iter0', 'Iter1'):
    t = pd.read_csv('$D/residual_fits_' + label + '.csv')
    print(label, len(t), 'rows', t.groupby('detector').size().to_dict(), t.fit_status.value_counts().to_dict())
"
```

Expected: 60 rows per label. That is MVTX 20 (9 chips and a stave row, two
coordinates), INTT 10, and VERTEX 30. There are no layer-20 rows.

### 2. Comparison (no AI)

```bash
python3 -m stdiag.compare_runs "$D/residual_fits_Iter0.csv" "$D/residual_fits_Iter1.csv" --out-dir "$OUT"
```

Expected: `Iter1 vs Iter0: 10 flagged of 57 comparable (3 not comparable)`.
Read `$OUT/report_Iter0_vs_Iter1.md`.

### 3. Check the flags against the truth (no AI)

```bash
python3 -m synthetic.stavechip_demo.check_demo "$OUT/flags_Iter0_vs_Iter1.csv" --tables "$D"
```

It lists every entry that is not unchanged and ends with `PASS`:
- the three silicon flags: chips 3 and 5 and INTT sensor 2 z;
- the two not-comparable chips, 7 and 8. Chip 8 is a lesson: a chip that
  moved back from +800 µm is not *flagged* but *not comparable*, so always
  read the not-comparable list too;
- seven dca_xy φ bins, between +16.5 and −12.3 µm.

### 4. Vertex fit (no AI)

```bash
cut -d, -f1,3-8 "$D/vertex_phi_fit_Iter0.csv" "$D/vertex_phi_fit_Iter1.csv"
```

Expected: Iter0 A = 29.9 µm, φ0 = −0.004 rad; Iter1 A = 22.2 µm, φ0 = 0.475 rad.

### 5. Triage (dry run, then AI)

```bash
python3 -m stdiag.triage_agent "$OUT/flags_Iter0_vs_Iter1.csv" "$OUT/summary_Iter0_vs_Iter1.json" --backend claude-code --dry-run | less
python3 -m stdiag.triage_agent "$OUT/flags_Iter0_vs_Iter1.csv" "$OUT/summary_Iter0_vs_Iter1.json" --backend claude-code
```

The second command sends the synthetic summary to Anthropic (about $0.50).
A good answer has these properties:
- `validation passed`;
- chips 3 and 5 are single-chip shifts (B);
- INTT sensor 2 z is B, and is noted as indicative only;
- the seven φ bins form one coherent sinusoidal VERTEX finding (A), with
  amplitude and phase, kept apart from the chips;
- chips 7 and 8 are in E, with chip 8's `out_of_range` called out.

### 6. Review (optional, AI)

```bash
python3 -m stdiag.review list "$OUT/findings_Iter0_vs_Iter1.json"
python3 -m stdiag.review show "$OUT/findings_Iter0_vs_Iter1.json" F1
python3 -m stdiag.review ask "$OUT/findings_Iter0_vs_Iter1.json" F1 --since 2026-10-01 --no-dialogue --dry-run
```

The changes are synthetic, so this is a null test for the coresoftware
expert: the right answer is "no code change explains this". Run `ask` without
`--dry-run` only against a throwaway clone of coresoftware
(`export STDIAG_CORESOFTWARE=...`).

### 7. Why the current fit matters (no AI)

```bash
python3 -m stdiag.compare_runs "$PWD/synthetic/stavechip_demo/reference/before/residual_fits_Iter0.csv" "$PWD/synthetic/stavechip_demo/reference/before/residual_fits_Iter1.csv" --out-dir "$OUT/before"
python3 -m synthetic.stavechip_demo.check_demo "$OUT/before/flags_Iter0_vs_Iter1.csv"
```

With the old settings (histogram range = plotted range, Gaussian fit for
INTT z, no `out_of_range`), the check fails in four entries:
- the INTT z shift is missed on sensor 2;
- sensors 1 and 3 are flagged instead;
- chip 5 becomes `low_stats` instead of a −300 µm shift.

The reference tables were made with ROOT 6.40/04 on macOS (arm64), and
`run_demo.sh` reproduces them byte for byte there.
