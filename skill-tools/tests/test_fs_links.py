from __future__ import annotations

import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

from skill_tools.fs_links import is_link_like
from skill_tools.source import LocalSource

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")


def junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True
    )


def test_junction_is_link_like(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    junction(tmp_path / "link", tmp_path / "real")
    assert is_link_like(tmp_path / "link")
    assert not (tmp_path / "link").is_symlink()
    assert not is_link_like(tmp_path / "real")


def test_local_source_skips_files_reached_through_a_junction(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "skills" / "a").mkdir(parents=True)
    (root / "skills" / "a" / "SKILL.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    # Not registered in info/exclude, so git lists the junction's contents.
    junction(root / "mirror", root / "skills")

    files = LocalSource(root)._visible_files()
    assert PurePosixPath("skills/a/SKILL.md") in files
    assert not any(path.parts[0] == "mirror" for path in files)
