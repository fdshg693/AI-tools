"""Make ``textgraph`` importable without an editable install first."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def make_git_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return root


def write_text(root: Path, rel: str, content: str) -> Path:
    path = root.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    return make_git_repo(tmp_path / "repo")


@pytest.fixture
def write():
    return write_text
