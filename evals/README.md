# Evaluation layer

Measures the AI agents, one eval per agent. Each eval needs the reviewer's
sign-off on its test cases and on its grading before any paid run. Graders
are code wherever the output allows it; AI judges only where judgment is
genuinely needed.

| Eval | Measures | Inputs | Grading | Status |
|---|---|---|---|---|
| `triage/` | Does the triage group flags correctly without inventing findings? | Synthetic comparisons with known injected changes, including no-change and distractor cases | Code, from `findings_*.json` against the injected truth | Cases proposed (`triage/PROPOSED_CASES.md`), awaiting sign-off |
| `coresoftware_expert/` | Does the expert find the commit behind a known effect? | Past coresoftware commits with a known residual effect, described as findings | Code: commit hit in top 1 / top 3; every cited hash checked with git | Planned |
| `tracking_expert/` | Are its verdicts right? | Hypotheses with known verdicts (correct, sign-flipped residual, ACTS API absent in v45) | Code: verdict label | Planned |
| `permissions/` | Do the read-only and web-domain limits hold? | Prompts that try to edit files, run forbidden commands or fetch disallowed sites | End state: checkout unchanged, nothing forbidden fetched | Planned |
| `dialogue/` | How do the two experts converge? | Findings with known causes | Convergence rate, turns used, questions to the reviewer, status-format compliance | Planned |

Run outputs (transcripts, reports) are git-ignored; cases, runners and
graders are committed.
