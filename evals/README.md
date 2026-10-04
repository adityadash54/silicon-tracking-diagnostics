# Evaluation layer

Measures the AI agents, one eval per agent. Each eval needs the reviewer's
sign-off on its test cases and on its grading before any paid run. Graders
are code wherever the output allows it; AI judges only where judgment is
genuinely needed.

| Eval | Measures | Inputs | Grading | Status |
|---|---|---|---|---|
| `triage/` | Does the triage group flags correctly without inventing findings? | Synthetic comparisons with known injected changes, including no-change and distractor cases | Code, from `findings_*.json` against the injected truth | Cases and grading approved (`triage/PROPOSED_CASES.md`); runner and grader built; self-test passes; pilot pending |
| `coresoftware_expert/` | Does the expert find the commit behind a known effect? | Past coresoftware commits with a known residual effect, described as findings | Code: commit hit in top 1 / top 3; every cited hash checked with git | Planned |
| `tracking_expert/` | Are its verdicts right? | Hypotheses with known verdicts (correct, sign-flipped residual, ACTS API absent in v45) | Code: verdict label | Planned |
| `permissions/` | Do the read-only and web-domain limits hold? | Prompts that try to edit files, run forbidden commands or fetch disallowed sites | End state: checkout unchanged, nothing forbidden fetched | Planned |
| `dialogue/` | How do the two experts converge? | Findings with known causes | Convergence rate, turns used, questions to the reviewer, status-format compliance | Planned |

Run outputs (transcripts, reports) are git-ignored; cases, runners and
graders are committed.

## Triage eval

```bash
python evals/triage/run_eval.py --self-test        # grader check, no AI
python evals/triage/run_eval.py --approve-harness  # reviewer only; records a checksum
python evals/triage/run_eval.py --cases null-1,stave-mvtx-rphi,mixed-1 --reps 1   # pilot
python evals/triage/run_eval.py --reps 2           # full run: 21 cases x 2
```

The runner refuses to start until the reviewer has approved the current
harness files (runner, cases, grader, triage, comparison, generator); any
change to them requires a new approval. Results are in
`evals/triage/runs/baseline/` (`results.jsonl`, `traces/`, `errors.jsonl`).
With 21 cases × 2 repetitions, the pass rate has a noise floor of roughly
±15 percentage points, so smaller differences between variants are not
meaningful.
