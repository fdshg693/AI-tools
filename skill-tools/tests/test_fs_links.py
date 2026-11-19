from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

from skill_tools.fs_links import (
    create_dir_link,
    is_link_like,
    link_target,
    remove_link,
    same_link_target,
)
from skill_tools.source import LocalSource

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")


def junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True
    )


def _real_dir(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("x\n", encoding="utf-8")
    return path


@windows_only
def test_junction_is_link_like(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    junction(tmp_path / "link", tmp_path / "real")
    assert is_link_like(tmp_path / "link")
    assert not (tmp_path / "link").is_symlink()
    assert not is_link_like(tmp_path / "real")


@windows_only
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


def test_create_dir_link_round_trip(tmp_path: Path) -> None:
    target = _real_dir(tmp_path / "store" / "alpha")
    link = tmp_path / "project" / ".claude" / "skills" / "alpha"

    create_dir_link(link, target)

    assert is_link_like(link)
    assert link_target(link) == target
    assert same_link_target(link, target)
    assert (link / "SKILL.md").read_text(encoding="utf-8") == "x\n"
    assert link.resolve() == target.resolve()

    remove_link(link)
    assert not link.exists() and not is_link_like(link)
    assert (target / "SKILL.md").is_file()


@pytest.mark.parametrize("name", ["a&b", "c^d", "e %PATH% f", "日本語 dir"])
def test_create_dir_link_handles_shell_special_characters(tmp_path: Path, name: str) -> None:
    target = _real_dir(tmp_path / f"target {name}")
    link = tmp_path / f"link {name}"
    create_dir_link(link, target)
    assert same_link_target(link, target)
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        [f"target {name}", f"link {name}"]
    )


def test_create_dir_link_refuses_existing_link_path(tmp_path: Path) -> None:
    target = _real_dir(tmp_path / "target")
    (tmp_path / "link").mkdir()
    with pytest.raises(FileExistsError):
        create_dir_link(tmp_path / "link", target)


def test_create_dir_link_refuses_missing_or_linked_target(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="existing real directory"):
        create_dir_link(tmp_path / "link", tmp_path / "missing")
    target = _real_dir(tmp_path / "target")
    create_dir_link(tmp_path / "link", target)
    with pytest.raises(OSError, match="existing real directory"):
        create_dir_link(tmp_path / "link2", tmp_path / "link")


def test_create_dir_link_makes_relative_target_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _real_dir(tmp_path / "target")
    monkeypatch.chdir(tmp_path)
    create_dir_link(tmp_path / "link", Path("target"))
    target = link_target(tmp_path / "link")
    assert target is not None and target.is_absolute()
    assert same_link_target(tmp_path / "link", tmp_path / "target")


def test_link_target_of_broken_link_and_non_links(tmp_path: Path) -> None:
    target = _real_dir(tmp_path / "target")
    link = tmp_path / "link"
    create_dir_link(link, target)
    shutil.rmtree(target)

    assert is_link_like(link)
    assert not link.exists()
    assert link_target(link) == target
    remove_link(link)
    assert not is_link_like(link)

    assert link_target(tmp_path / "missing") is None
    (tmp_path / "plain").mkdir()
    assert link_target(tmp_path / "plain") is None
    assert not same_link_target(tmp_path / "plain", tmp_path / "plain")


def test_remove_link_refuses_real_directory_and_file(tmp_path: Path) -> None:
    real = _real_dir(tmp_path / "real")
    with pytest.raises(OSError, match="non-link"):
        remove_link(real)
    with pytest.raises(OSError, match="non-link"):
        remove_link(real / "SKILL.md")
    assert (real / "SKILL.md").is_file()


@windows_only
def test_same_link_target_ignores_case_on_windows(tmp_path: Path) -> None:
    target = _real_dir(tmp_path / "Target")
    create_dir_link(tmp_path / "link", target)
    assert same_link_target(tmp_path / "link", Path(str(target).upper()))
