"""Locations the framework reads, overridable with environment variables.

STDIAG_CORESOFTWARE   coresoftware git checkout searched by the experts
                      (default: ../coresoftware next to this repository)
STDIAG_TRACKING_DOCS  ACTS / Millepede-II snapshot made by
                      `python -m stdiag.fetch_tracking_docs`
                      (default: tracking_docs/ in this repository, git-ignored)
STDIAG_RUNS_DIR       where compare_runs creates one folder per comparison,
                      runs/<a>_vs_<b> (default: runs/ in this repository,
                      git-ignored)
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPS_DIR = REPO_ROOT / "maps"
CODE_MAP = MAPS_DIR / "coresoftware_code_map.md"
DOCS_MAP = MAPS_DIR / "tracking_docs_map.md"

CORESOFTWARE = Path(os.environ.get(
    "STDIAG_CORESOFTWARE", REPO_ROOT.parent / "coresoftware")).resolve()
TRACKING_DOCS = Path(os.environ.get(
    "STDIAG_TRACKING_DOCS", REPO_ROOT / "tracking_docs")).resolve()
RUNS_DIR = Path(os.environ.get("STDIAG_RUNS_DIR", REPO_ROOT / "runs")).resolve()
