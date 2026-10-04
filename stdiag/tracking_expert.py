#!/usr/bin/env python3
"""Tracking expert (ACTS + Millepede-II): check a coresoftware expert answer.

Runs the Claude Code CLI (`claude -p`) inside the coresoftware checkout with
read-only tools: Read, Grep, Glob, read-only git commands, read access to
the tracking_docs/ snapshot (ACTS 45.0.0 from the sPHENIX fork, Millepede-II
manual V04-17-06; see fetch_tracking_docs.py), and WebFetch limited to
www.desy.de, acts-project.github.io, github.com and raw.githubusercontent.com
for anything the snapshot lacks. Anything else is refused without asking;
no MCP connectors are loaded; nothing is edited.

For each hypothesis in the coresoftware expert's answer it verifies the
cited code and judges whether the hypothesis is consistent with ACTS
conventions and Millepede-II procedures, citing documentation and code.

Sent to Anthropic: the finding, the coresoftware expert's answer, the docs
map, and the code, documentation and web pages the agent reads.

Normally called through `review.py check`; standalone use:
  python -m stdiag.tracking_expert finding.json expert_answer.md [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stdiag.coresoftware_expert import (
    ALLOWED_TOOLS, DEFAULT_MODEL, DEFAULT_REPO, DIALOGUE_PROTOCOL,
    DISALLOWED_TOOLS, describe_dry_run, find_claude, run_claude,
    session_arguments)
from stdiag.paths import DOCS_MAP, TRACKING_DOCS

DOCS_DIR = TRACKING_DOCS
WEB_DOMAINS = ["www.desy.de", "acts-project.github.io", "github.com",
               "raw.githubusercontent.com"]

TRACKING_PROMPT = """\
You are an expert in the ACTS tracking toolkit and in Millepede-II track-based \
alignment, reviewing hypotheses that a colleague (the coresoftware expert) \
produced about a change in sPHENIX MVTX/INTT residuals. You are read-only.

Sources, in order of preference:
1. The local snapshot in the tracking_docs directory (ACTS 45.0.0 from the \
sPHENIX fork, the version sPHENIX builds against; Millepede-II manual \
V04-17-06 with anchors written as {#anchor}). The docs map in the request \
says where each topic is.
2. sPHENIX code in the current directory (coresoftware) and its git history.
3. Web pages on www.desy.de, acts-project.github.io, github.com and \
raw.githubusercontent.com, only for what the snapshot lacks. On GitHub stay \
within acts-project and sPHENIX-Collaboration, and read ACTS at the sPHENIX \
fork's commit, not upstream main.

For every hypothesis in the colleague's answer:
- Check that the cited commits, files and lines exist and say what is claimed \
(git show, Read).
- Judge whether the proposed mechanism is consistent with ACTS conventions \
(geometry context and alignment transforms, surface local frames, \
measurement and bound-parameter definitions, residual = measurement - \
prediction) and, where alignment is involved, with Millepede-II procedures \
(residual and derivative sign consistency, unique global labels, constraints \
for weak modes, entries cut, outlier treatment, solution method).
- Verdict: consistent, partly consistent, inconsistent, or cannot verify.

Also check for version problems: if sPHENIX code uses ACTS API that differs \
from the 45.0.0 headers, say so. Do not present new hypotheses as findings; \
you may list additional checks. Cite each source as a snapshot path with \
anchor or line number plus its live URL, with a quote of at most two lines.

Answer in Markdown with these sections:
### Summary
### Hypothesis checks  (table: hypothesis, claim checked, code verified?, \
verdict, documentation evidence, sPHENIX code evidence)
### Procedure checks  (ACTS and Millepede-II requirements relevant here, and \
whether sPHENIX code meets them)
### Version caveats
### Sources consulted  (paths and URLs actually read)
"""


def build_request(finding: dict, expert_answer: str) -> str:
    sources = DOCS_DIR / "SOURCES.json"
    return "\n\n".join([
        "## Finding\n```json\n" + json.dumps(finding, indent=2) + "\n```",
        "## Coresoftware expert answer to check\n" + expert_answer,
        "## Docs map\n" + DOCS_MAP.read_text(),
        f"## Snapshot location\n{DOCS_DIR}\n\n```json\n"
        + (sources.read_text() if sources.exists() else "{}") + "\n```",
    ])


def claude_command(claude: str, model: str, effort: str,
                   session_id: str | None = None,
                   resume: bool = False) -> list[str]:
    """One-shot when session_id is None; otherwise a dialogue turn."""
    web_rules = [f"WebFetch(domain:{domain})" for domain in WEB_DOMAINS]
    prompt = TRACKING_PROMPT + (DIALOGUE_PROTOCOL if session_id else "")
    return [claude, "-p", "--output-format", "text", "--model", model,
            "--effort", effort,
            "--tools", "Read,Grep,Glob,Bash,WebFetch",
            "--allowedTools", *ALLOWED_TOOLS, *web_rules,
            "--disallowedTools", *DISALLOWED_TOOLS,
            "--permission-mode", "dontAsk",
            "--add-dir", str(DOCS_DIR),
            "--strict-mcp-config", *session_arguments(session_id, resume),
            "--append-system-prompt", prompt]


def require_inputs(repo: Path) -> None:
    if not (DOCS_DIR / "SOURCES.json").exists():
        sys.exit(f"ERROR: no snapshot in {DOCS_DIR}; run "
                 "`python -m stdiag.fetch_tracking_docs` first.")
    if not (repo / ".git").exists():
        sys.exit(f"ERROR: {repo} is not a git checkout.")


def check_answer(finding: dict, expert_answer: str,
                 repo: Path = DEFAULT_REPO, model: str = DEFAULT_MODEL,
                 effort: str = "high", dry_run: bool = False) -> str:
    """Return the tracking expert's Markdown review (or the request)."""
    require_inputs(repo)
    request = build_request(finding, expert_answer)
    if dry_run:
        return describe_dry_run(TRACKING_PROMPT, request, repo,
                                claude_command("claude", model, effort))
    return run_claude(claude_command(find_claude(), model, effort), request,
                      repo, "tracking expert")


def tracking_turn(text: str, session_id: str, resume: bool,
                  repo: Path = DEFAULT_REPO, model: str = DEFAULT_MODEL,
                  effort: str = "high") -> str:
    """One dialogue turn of the tracking expert in its own session."""
    require_inputs(repo)
    return run_claude(
        claude_command(find_claude(), model, effort, session_id, resume),
        text, repo, "tracking expert")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("finding", type=Path, help="JSON file with the finding")
    parser.add_argument("answer", type=Path,
                        help="coresoftware expert answer (Markdown)")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="high",
                        choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(check_answer(json.loads(args.finding.read_text()),
                       args.answer.read_text(), args.repo, args.model,
                       args.effort, args.dry_run))


if __name__ == "__main__":
    main()
