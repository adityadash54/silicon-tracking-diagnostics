"""Shared fixtures: synthetic comparison outputs and a scratch git repository."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_module(module: str, *args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        [sys.executable, "-m", module, *args], cwd=cwd or REPO_ROOT,
        capture_output=True, text=True,
        env={"PYTHONPATH": str(REPO_ROOT), "PYTHONDONTWRITEBYTECODE": "1",
             "PATH": "/usr/bin:/bin"})
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture(scope="session")
def synthetic_outputs(tmp_path_factory) -> Path:
    """Synthetic fit tables (seed 20261001) compared by compare_runs."""
    out = tmp_path_factory.mktemp("synthetic")
    run_module("synthetic.make_synthetic_fit_tables", "--out-dir", str(out))
    run_module("stdiag.compare_runs", *(str(out / f"residual_fits_{label}.csv")
                                        for label in ("Iter0", "Iter1", "Iter2")),
               "--out-dir", str(out))
    return out


@pytest.fixture()
def findings_file(tmp_path, synthetic_outputs) -> Path:
    """A findings file covering two Iter1 findings, next to its flags table."""
    flags = synthetic_outputs / "flags_Iter0_vs_Iter1.csv"
    (tmp_path / flags.name).write_bytes(flags.read_bytes())
    findings = {
        "reference": {"label": "Iter0", "listfile": "ntuple_list1.txt"},
        "comparison": {"label": "Iter1", "listfile": "ntuple_list2.txt"},
        "source": {"flags": flags.name}, "validation": {"passed": True},
        "findings": [
            {"id": "F1", "group": "A", "priority": 1,
             "title": "MVTX L1 stave 4 r-phi shift",
             "entries": [{"detector": "MVTX", "layer": 1, "stave": 4,
                          "chip": chip, "coord": "rphi"} for chip in range(9)]},
            {"id": "F2", "group": "C", "priority": 2,
             "title": "MVTX L0 stave 2 chip 5 wider",
             "entries": [{"detector": "MVTX", "layer": 0, "stave": 2,
                          "chip": 5, "coord": coord}
                         for coord in ("rphi", "z")]},
        ],
    }
    path = tmp_path / "findings_Iter0_vs_Iter1.json"
    path.write_text(json.dumps(findings))
    return path


@pytest.fixture()
def git_repo(tmp_path) -> tuple[Path, list[str]]:
    """A scratch git repository with two commits."""
    repo = tmp_path / "repo"
    repo.mkdir()
    commits = []
    for index in range(2):
        (repo / "file.txt").write_text(f"version {index}\n")
        for command in (["git", "init", "-q"] if index == 0 else [],
                        ["git", "add", "file.txt"],
                        ["git", "-c", "user.name=t", "-c", "user.email=t@t",
                         "commit", "-q", "-m", f"commit {index}"]):
            if command:
                subprocess.run(command, cwd=repo, check=True)
        commits.append(subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            capture_output=True, text=True).stdout.strip())
    return repo, commits
