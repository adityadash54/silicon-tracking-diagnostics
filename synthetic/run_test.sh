#!/usr/bin/env bash
# Runs the framework on synthetic fit tables with known injected changes.
# The ROOT fit step is replaced by synthetic/make_synthetic_fit_tables.py;
# comparison and triage are the real stdiag modules.
#   synthetic/run_test.sh          comparison + truth check + triage dry run
#                                  (nothing leaves this machine)
#   synthetic/run_test.sh --ai     also runs the triage through the API
#                                  (needs the anthropic package and
#                                  ANTHROPIC_API_KEY or `ant auth login`)
#   synthetic/run_test.sh --ai-claude-code
#                                  also runs the triage through the Claude
#                                  Code CLI (your Claude Code login)
# Both AI options send the synthetic summary rows to Anthropic.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_DIR}/synthetic/output"
PYTHON="${PYTHON:-python3}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="${REPO_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

cd "${REPO_DIR}"
rm -rf "${OUT_DIR}"
"${PYTHON}" -m synthetic.make_synthetic_fit_tables --out-dir "${OUT_DIR}"

"${PYTHON}" -m stdiag.compare_runs \
  "${OUT_DIR}/residual_fits_Iter0.csv" \
  "${OUT_DIR}/residual_fits_Iter1.csv" \
  "${OUT_DIR}/residual_fits_Iter2.csv" \
  --out-dir "${OUT_DIR}"

status=0
for comparison in Iter1 Iter2; do
  stem="Iter0_vs_${comparison}"
  "${PYTHON}" -m synthetic.check_against_truth \
    "${OUT_DIR}/flags_${stem}.csv" "${OUT_DIR}/summary_${stem}.json" \
    | tee "${OUT_DIR}/truth_check_${stem}.txt" || status=1

  "${PYTHON}" -m stdiag.triage_agent \
    "${OUT_DIR}/flags_${stem}.csv" "${OUT_DIR}/summary_${stem}.json" \
    --dry-run > "${OUT_DIR}/triage_dry_run_${stem}.txt"

  case "${1:-}" in
    --ai)
      "${PYTHON}" -m stdiag.triage_agent \
        "${OUT_DIR}/flags_${stem}.csv" "${OUT_DIR}/summary_${stem}.json"
      ;;
    --ai-claude-code)
      "${PYTHON}" -m stdiag.triage_agent \
        "${OUT_DIR}/flags_${stem}.csv" "${OUT_DIR}/summary_${stem}.json" \
        --backend claude-code
      ;;
  esac
done

exit "${status}"
