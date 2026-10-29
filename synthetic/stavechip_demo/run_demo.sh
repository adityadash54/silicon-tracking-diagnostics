#!/usr/bin/env bash
# Stave/chip demo: one MVTX stave and one INTT ladder with known shifts
# (make_synth.C), fitted twice with macros/plot_fits_overlaid_stavechip.C:
#   after/   the current macro
#   before/  the same macro with the old fit settings (histogram range =
#            plotted range, Gaussian fit for INTT z, no out_of_range status)
# then compared with stdiag.compare_runs and checked against the injected
# truth (check_demo.py). The "after" check must pass; the "before" check
# shows what the old settings got wrong. Needs ROOT; nothing leaves this
# machine. Output: synthetic/stavechip_demo/output/ (deleted on each run).
#   synthetic/stavechip_demo/run_demo.sh
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${DEMO_DIR}/../.." && pwd)"
OUT_DIR="${DEMO_DIR}/output"
PYTHON="${PYTHON:-python3}"
MACRO="${REPO_DIR}/macros/plot_fits_overlaid_stavechip.C"

command -v root > /dev/null || { echo "ERROR: root is not on PATH" >&2; exit 2; }
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="${REPO_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}/after" "${OUT_DIR}/before"
cd "${OUT_DIR}"

echo "== 1. Synthetic ROOT files"
cp "${DEMO_DIR}/make_synth.C" .
root -l -b -q make_synth.C > make_synth.log 2>&1
for label in Iter0 Iter1; do
  [[ -s "synth${label}.root" ]] || { echo "ERROR: synth${label}.root not written; see ${OUT_DIR}/make_synth.log" >&2; exit 1; }
  echo "${OUT_DIR}/synth${label}.root" > "list_${label}.txt"
done

echo "== 2. Fit macro, current (after/) and old settings (before/)"
cp "${MACRO}" after/
"${PYTHON}" - "${MACRO}" before/plot_fits_overlaid_stavechip.C <<'EOF'
import sys
text = open(sys.argv[1]).read()
replacements = [
    ("0.05, 0.5, 0.015, 0.05, 0.5, 0.015, false};",
     "0.05, 0.05, 0.015, 0.05, 0.05, 0.015, false};"),
    ("0.6, 3.0, 0.2, 20.0, 40.0, 5.0, true};",
     "0.6, 0.6, 0.2, 20.0, 20.0, 5.0, false};"),
    ("constexpr double kMaximumOutOfRangeFraction = 0.5;",
     "constexpr double kMaximumOutOfRangeFraction = 2.0;"),
]
for old, new in replacements:
    if text.count(old) != 1:
        sys.exit("ERROR: the fit macro changed; update the 'before' "
                 f"settings in run_demo.sh (not found once: {old})")
    text = text.replace(old, new)
open(sys.argv[2], "w").write(text)
EOF

status=0
for version in after before; do
  (cd "${version}" &&
   root -l -b -q "plot_fits_overlaid_stavechip.C+(\"../list_Iter0.txt:Iter0,../list_Iter1.txt:Iter1\",\"residual_fits_${version}.pdf\",true)" \
     > plot_fits.log 2>&1 || true)
  [[ -s "${version}/residual_fits_Iter1.csv" ]] || { echo "ERROR: ${version}/residual_fits_Iter1.csv not written; see ${OUT_DIR}/${version}/plot_fits.log" >&2; exit 1; }
  grep -E "A\*sin|Wrote [0-9]+ rows" "${version}/plot_fits.log" | sed "s/^/  ${version}: /"

  echo "== 3. Comparison (${version})"
  "${PYTHON}" -m stdiag.compare_runs "${version}/residual_fits_Iter0.csv" \
    "${version}/residual_fits_Iter1.csv" --out-dir "${version}/comparison" | sed 's/ ->.*//'

  echo "== 4. Truth check (${version})"
  if "${PYTHON}" -m synthetic.stavechip_demo.check_demo \
       "${version}/comparison/flags_Iter0_vs_Iter1.csv" --tables "${version}" \
       > "${version}/truth_check.txt"; then
    echo "  $(tail -1 "${version}/truth_check.txt")"
    [[ "${version}" == after ]] || echo "  (unexpected: the old settings should fail)"
  else
    if [[ "${version}" == after ]]; then
      status=1
      cat "${version}/truth_check.txt"
    else
      echo "  as expected, the old settings disagree with the truth:"
      sed -n '/FAIL/,$p' "${version}/truth_check.txt" | sed 's/^/  /'
    fi
  fi
done

echo "Outputs in ${OUT_DIR} (plots: after/residual_fits_after.pdf, before/residual_fits_before.pdf)"
exit "${status}"
