#!/usr/bin/env python3
"""Snapshot the ACTS and Millepede-II references read by tracking_expert.py.

Writes tracking_docs/:
  acts/docs/...           Markdown/Doxygen sources of the ACTS docs
  acts/Core/include/...   ACTS core headers (ground truth for conventions)
  acts/version_number     ACTS version of the snapshot
  millepede/draftman_page.html, draftman_page.txt
                          Millepede-II draft manual; the .txt keeps anchors
                          as {#anchor} markers so they can be cited
  SOURCES.json            where everything came from (repo, ref, commit, time)

The ACTS files come from the sPHENIX fork (the version sPHENIX builds
against), not upstream main. Re-run to refresh; it replaces tracking_docs/.

Usage:
  python -m stdiag.fetch_tracking_docs [--acts-ref sPHENIX] [--out tracking_docs]
"""

from __future__ import annotations

import argparse
import datetime as dt
import html.parser
import json
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from stdiag.paths import TRACKING_DOCS

ACTS_REPO = "https://github.com/sPHENIX-Collaboration/acts.git"
MILLEPEDE_URL = "https://www.desy.de/~kleinwrt/MP2/doc/html/draftman_page.html"
DOC_SUFFIXES = {".md", ".dox", ".bib"}


class TextWithAnchors(html.parser.HTMLParser):
    """HTML to plain text, marking id/name anchors as {#anchor}."""

    BREAK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4",
                  "h5", "h6", "pre", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        anchor = dict(attrs).get("id") or dict(attrs).get("name")
        if anchor:
            self.parts.append(f" {{#{anchor}}} ")
        if tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self.parts)
                 .splitlines())
        return "\n".join(line for line in lines if line) + "\n"


def run(command: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def fetch_acts(ref: str, destination: Path) -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        clone = Path(temporary) / "acts"
        run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none",
             "--sparse", "--branch", ref, ACTS_REPO, str(clone)])
        run(["git", "sparse-checkout", "set", "docs", "Core/include"],
            cwd=clone)
        commit = run(["git", "rev-parse", "HEAD"], cwd=clone)
        date = run(["git", "log", "-1", "--format=%cI"], cwd=clone)

        for path in (clone / "docs").rglob("*"):
            if path.is_file() and path.suffix in DOC_SUFFIXES:
                target = destination / "docs" / path.relative_to(clone / "docs")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        shutil.copytree(clone / "Core" / "include",
                        destination / "Core" / "include")
        shutil.copy2(clone / "version_number", destination / "version_number")
        version = (clone / "version_number").read_text().strip()
    return {"repository": ACTS_REPO, "ref": ref, "commit": commit,
            "commit_date": date, "version_number": version}


def fetch_millepede(destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(MILLEPEDE_URL, timeout=60) as response:
        page = response.read().decode("utf-8", errors="replace")
    (destination / "draftman_page.html").write_text(page)
    parser = TextWithAnchors()
    parser.feed(page)
    (destination / "draftman_page.txt").write_text(parser.text())
    return {"url": MILLEPEDE_URL}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--acts-ref", default="sPHENIX",
                        help="branch or tag of the sPHENIX ACTS fork")
    parser.add_argument("--out", type=Path,
                        default=TRACKING_DOCS)
    args = parser.parse_args()

    if args.out.exists():
        shutil.rmtree(args.out)
    sources = {
        "fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"),
        "acts": fetch_acts(args.acts_ref, args.out / "acts"),
        "millepede": fetch_millepede(args.out / "millepede"),
    }
    (args.out / "SOURCES.json").write_text(json.dumps(sources, indent=2)
                                           + "\n")
    print(json.dumps(sources, indent=2))


if __name__ == "__main__":
    main()
