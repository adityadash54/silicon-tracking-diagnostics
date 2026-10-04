"""review.py and the expert dialogue with scripted agents (no AI calls)."""

from __future__ import annotations

import contextlib
import io
import json
import sys

import pytest

from stdiag import expert_dialogue, review


def reply(status, message="msg", question="", body="Body."):
    return (f"{body}\n\n```json\n" + json.dumps({
        "status": status, "message_to_other": message,
        "question_for_human": question, "summary": f"{status} summary"})
        + "\n```")


@pytest.fixture()
def scripted(monkeypatch):
    """Replace both experts with scripted replies; records every call."""
    calls = []

    def install(replies):
        queue = iter(replies)

        def make(agent):
            def turn(text, session_id, resume, repo, model, effort):
                calls.append({"agent": agent, "text": text,
                              "session": session_id, "resume": resume})
                return next(queue)
            return turn
        monkeypatch.setattr(expert_dialogue, "TURN_FUNCTIONS",
                            {agent: make(agent) for agent in expert_dialogue.AGENTS})
        return calls
    return install


def cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["review", "--reviewer", "tester", *argv])
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            review.main()
    except SystemExit as error:
        output.write(f"[exit] {error}")
    return output.getvalue()


def latest_state(findings_file):
    events = json.loads(findings_file.with_name(
        "review_Iter0_vs_Iter1.json").read_text())
    dialogue = [event for event in events if event["type"] == "dialogue"][-1]
    return json.loads(findings_file.with_name(dialogue["state_file"]).read_text())


def turns(state):
    return [f"{entry['agent'][0].upper()}{entry['turn']}:{entry['status']}"
            for entry in state["turn_log"]]


def ask(monkeypatch, findings_file, finding, repo, commits):
    return cli(monkeypatch, "ask", str(findings_file), finding, "--repo",
               str(repo), "--from", commits[0], "--to", commits[1])


def test_converges(monkeypatch, findings_file, git_repo, scripted):
    repo, commits = git_repo
    calls = scripted([reply("continue", body="Hypothesis H1"),
                      reply("continue"), reply("converged")])
    ask(monkeypatch, findings_file, "F1", repo, commits)
    state = latest_state(findings_file)
    assert state["status"] == "converged"
    assert turns(state) == ["C1:continue", "T1:continue", "C2:converged"]
    assert [call["resume"] for call in calls] == [False, False, True]
    assert "Hypothesis H1" in calls[1]["text"]


def test_limit_pause_and_continue(monkeypatch, findings_file, git_repo,
                                  scripted):
    repo, commits = git_repo
    calls = scripted([reply("continue")] * 6 + [reply("converged")])
    ask(monkeypatch, findings_file, "F1", repo, commits)
    state = latest_state(findings_file)
    assert state["status"] == "paused_at_limit"
    assert state["turns_this_round"] == {"coresoftware": 3, "tracking": 3}
    assert "awaiting your approval" in cli(monkeypatch, "list", str(findings_file))

    cli(monkeypatch, "continue", str(findings_file), "F1", "--note", "Focus X")
    state = latest_state(findings_file)
    assert (state["status"], state["round"]) == ("converged", 2)
    assert "Focus X" in calls[-1]["text"]
    assert calls[-1]["session"] == calls[0]["session"]
    assert "not paused" in cli(monkeypatch, "continue", str(findings_file), "F1")


def test_question_for_reviewer(monkeypatch, findings_file, git_repo,
                               scripted):
    repo, commits = git_repo
    calls = scripted([reply("continue"),
                      reply("needs_human", question="Which CDB tag?"),
                      reply("converged")])
    ask(monkeypatch, findings_file, "F2", repo, commits)
    state = latest_state(findings_file)
    assert (state["status"], state["next_agent"]) == ("needs_human", "tracking")
    cli(monkeypatch, "continue", str(findings_file), "F2", "--note", "tag X")
    assert latest_state(findings_file)["status"] == "converged"
    assert "tag X" in calls[-1]["text"]
    assert "Message from the" not in calls[-1]["text"]


def test_missing_status_block_and_early_convergence(monkeypatch, findings_file,
                                                    git_repo, scripted):
    repo, commits = git_repo
    scripted(["Plain answer", reply("continue"), reply("converged")])
    ask(monkeypatch, findings_file, "F1", repo, commits)
    state = latest_state(findings_file)
    assert [entry["protocol_ok"] for entry in state["turn_log"]] == [False, True, True]

    scripted([reply("converged"), reply("converged")])
    ask(monkeypatch, findings_file, "F1", repo, commits)
    assert turns(latest_state(findings_file)) == ["C1:converged", "T1:converged"]


def test_bad_revision_and_missing_range(monkeypatch, findings_file, git_repo):
    repo, commits = git_repo
    assert "is not a commit" in cli(monkeypatch, "ask", str(findings_file),
                                    "F1", "--repo", str(repo), "--from",
                                    "nosuchrev", "--to", commits[1])
    assert "pass --since" in cli(monkeypatch, "ask", str(findings_file), "F1",
                                 "--repo", str(repo), "--labels",
                                 str(findings_file.with_name("none.csv")))


def test_output_names_unique_with_dotted_labels(tmp_path):
    findings = tmp_path / "findings_ana.499_vs_ana.500.json"
    first = review.new_output_base(findings, "dialogue", "F1")
    first.with_name(first.name + ".md").write_text("x")
    second = review.new_output_base(findings, "dialogue", "F1")
    assert first.name.startswith("dialogue_ana.499_vs_ana.500_F1_")
    assert second.name == first.name + "_2"


def test_decide_is_logged(monkeypatch, findings_file):
    cli(monkeypatch, "decide", str(findings_file), "F2", "needs-info",
        "--note", "check cluster size")
    assert "[needs-info]" in cli(monkeypatch, "list", str(findings_file))
    log = findings_file.with_name("review_Iter0_vs_Iter1.md").read_text()
    assert "check cluster size" in log
