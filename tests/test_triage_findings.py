"""Triage output handling with canned AI responses (no AI calls)."""

from __future__ import annotations

import json
import sys

import pytest

from stdiag import triage_agent

STAVE = [{"detector": "MVTX", "layer": 1, "stave": 4, "chip": chip,
          "coord": "rphi"} for chip in range(9)]
REST = [{"detector": "MVTX", "layer": 0, "stave": 2, "chip": 5, "coord": "rphi"},
        {"detector": "MVTX", "layer": 0, "stave": 2, "chip": 5, "coord": "z"},
        {"detector": "MVTX", "layer": 2, "stave": 10, "chip": 3, "coord": "z"},
        {"detector": "INTT", "layer": 4, "stave": 6, "chip": 1, "coord": "rphi"}]
GOOD = [{"id": "F1", "group": "A", "title": "stave shift", "priority": 1,
         "entries": STAVE},
        {"id": "F2", "group": "B", "title": "the rest", "priority": 2,
         "entries": REST}]
GHOST = {"id": "F3", "group": "B", "title": "ghost", "priority": 3,
         "entries": [{"detector": "MVTX", "layer": 9, "stave": 0, "chip": 0,
                      "coord": "z"}]}


def response(findings):
    return ("### Overview\nText.\n\n```json\n"
            + json.dumps({"findings": findings}) + "\n```\n")


@pytest.mark.parametrize("text, passed, unassigned, unknown", [
    (response(GOOD), True, 0, 0),
    (response(GOOD[:1]), False, 4, 0),
    (response(GOOD + [GHOST]), False, 0, 1),
    ("### Overview\nNo block.", False, 0, 0),
])
def test_findings_validation(tmp_path, synthetic_outputs, monkeypatch, text,
                             passed, unassigned, unknown):
    for name in ("flags_Iter0_vs_Iter1.csv", "summary_Iter0_vs_Iter1.json"):
        (tmp_path / name).write_bytes((synthetic_outputs / name).read_bytes())
    monkeypatch.setattr(triage_agent, "run_triage_claude_code",
                        lambda summary, model: (text, "canned"))
    monkeypatch.setattr(sys, "argv", [
        "triage_agent", str(tmp_path / "flags_Iter0_vs_Iter1.csv"),
        str(tmp_path / "summary_Iter0_vs_Iter1.json"),
        "--backend", "claude-code"])
    triage_agent.main()

    findings = json.loads((tmp_path / "findings_Iter0_vs_Iter1.json").read_text())
    validation = findings["validation"]
    assert validation["passed"] is passed
    assert len(validation.get("unassigned_flagged", [])) == unassigned
    assert len(validation.get("unknown_entries", [])) == unknown
    report = (tmp_path / "triage_report_Iter0_vs_Iter1.md").read_text()
    assert "```json" not in report
    assert ("validation passed" in report) is passed


def test_dry_run_sends_no_injection_truth(synthetic_outputs, capsys,
                                          monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "triage_agent", str(synthetic_outputs / "flags_Iter0_vs_Iter1.csv"),
        str(synthetic_outputs / "summary_Iter0_vs_Iter1.json"),
        "--backend", "claude-code", "--dry-run"])
    triage_agent.main()
    prompt = capsys.readouterr().out
    assert "list_notable_unflagged" in prompt
    for leaked in ("inject", "stave_shift_rphi", "synthetic"):
        assert leaked not in prompt.lower()
