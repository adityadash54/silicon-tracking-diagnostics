#!/usr/bin/env bash
# Runs the whole pipeline, starting from ROOT files, on synthetic data with
# known injected changes:
#   1. injections.csv          synthetic.make_synthetic_fit_tables
#   2. synth_<label>.root      synthetic/make_synthetic_ntp.C (ntp + track_ntp)
#   3. residual_fits_<label>.csv
#                              macros/plot_fits_overlaid_stavechip.C
#   4. flags, summary, report  stdiag.compare_runs
#   5. truth check             synthetic.check_against_truth
#   6. fit tables vs synthetic/reference/
#                              synthetic.compare_to_reference
#   7. triage dry run          stdiag.triage_agent --dry-run
#
#   synthetic/run_full_pipeline.sh [--plots] [--ai-claude-code] [--out-dir DIR]
#     --plots           also write the PDF/PNG residual plots (slower)
#     --ai-claude-code  also run the AI triage through the Claude Code CLI
#                       (sends the synthetic flag summary to Anthropic)
#     --out-dir DIR     output directory (default synthetic/pipeline_output;
#                       its previous contents are deleted)
# Needs ROOT (root on PATH) and Python with numpy and pandas. Without
# --ai-claude-code nothing leaves this machine. The ROOT files are about 20 MB
# each; the macros are compiled (ACLiC) in the output directory.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_DIR}/synthetic/pipeline_output"
PYTHON="${PYTHON:-python3}"
MAKE_PLOTS=false
RUN_AI=false
LABELS=(Iter0 Iter1 Iter2)
MARKER=".stdiag_pipeline_output"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plots) MAKE_PLOTS=true ;;
    --ai-claude-code) RUN_AI=true ;;
    --out-dir) OUT_DIR="$(mkdir -p "$2" && cd "$2" && pwd)"; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

command -v root > /dev/null || { echo "ERROR: root is not on PATH" >&2; exit 2; }
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="${REPO_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

# Only delete a directory this script created.
if [[ -d "${OUT_DIR}" && -n "$(ls -A "${OUT_DIR}")" && ! -e "${OUT_DIR}/${MARKER}" ]]; then
  echo "ERROR: ${OUT_DIR} is not empty and was not made by this script" >&2
  exit 2
fi
rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"
touch "${OUT_DIR}/${MARKER}"
cd "${OUT_DIR}"

echo "== 1. Injected truth"
"${PYTHON}" -c "from synthetic.make_synthetic_fit_tables import injection_table; injection_table().to_csv('injections.csv', index=False)"

# Runs a ROOT macro with its log in <log>, shows the key lines and stops if
# an expected output file is missing.
run_root() {
  local log="$1" macro_call="$2"
  shift 2
  root -l -b -q "${macro_call}" > "${log}" 2>&1 || true
  grep -E "Wrote|ERROR|WARNING|A\*sin" "${log}" || true
  for expected in "$@"; do
    [[ -s "${expected}" ]] || { echo "ERROR: ${expected} was not written; see ${OUT_DIR}/${log}" >&2; exit 1; }
  done
}

echo "== 2. Synthetic ROOT files"
cp "${REPO_DIR}/synthetic/make_synthetic_ntp.C" .
run_root make_synthetic_ntp.log 'make_synthetic_ntp.C+("injections.csv",".")' \
  synth_Iter0.root synth_Iter1.root synth_Iter2.root

echo "== 3. Per-chip fits"
cp "${REPO_DIR}/macros/plot_fits_overlaid_stavechip.C" .
inputs=""
for label in "${LABELS[@]}"; do
  echo "${OUT_DIR}/synth_${label}.root" > "list_${label}.txt"
  inputs+="${inputs:+,}list_${label}.txt:${label}"
done
if ${MAKE_PLOTS}; then
  call="plot_fits_overlaid_stavechip.C+(\"${inputs}\",\"synthetic_residual_fits.pdf\",true)"
else
  call="plot_fits_overlaid_stavechip.C+(\"${inputs}\",\"\",false,true,true,0.0,true,\".\",false)"
fi
run_root plot_fits.log "${call}" \
  residual_fits_Iter0.csv residual_fits_Iter1.csv residual_fits_Iter2.csv

echo "== 4. Comparison"
"${PYTHON}" -m stdiag.compare_runs residual_fits_Iter0.csv residual_fits_Iter1.csv \
  residual_fits_Iter2.csv --out-dir . | sed 's/ ->.*//'

status=0
echo "== 5. Truth check"
for comparison in Iter1 Iter2; do
  stem="Iter0_vs_${comparison}"
  "${PYTHON}" -m synthetic.check_against_truth "flags_${stem}.csv" "summary_${stem}.json" \
    > "truth_check_${stem}.txt" || status=1
  echo "${comparison}: $(tail -1 "truth_check_${stem}.txt")"
done

echo "== 6. Comparison with synthetic/reference/"
"${PYTHON}" -m synthetic.compare_to_reference . || status=1

echo "== 7. Triage"
for comparison in Iter1 Iter2; do
  stem="Iter0_vs_${comparison}"
  "${PYTHON}" -m stdiag.triage_agent "flags_${stem}.csv" "summary_${stem}.json" \
    --backend claude-code --dry-run > "triage_dry_run_${stem}.txt"
  if ${RUN_AI}; then
    "${PYTHON}" -m stdiag.triage_agent "flags_${stem}.csv" "summary_${stem}.json" \
      --backend claude-code
  fi
done
echo "Outputs in ${OUT_DIR}"
exit "${status}"
