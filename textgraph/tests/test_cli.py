from __future__ import annotations

from pathlib import Path

import pytest

from textgraph.cli import main
from textgraph.scan import is_script_file, is_text_file, sync_index
from textgraph.store import INDEX_DIR
from textgraph.store import db_path


def test_version_prints_command_and_manifest_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--version"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == ["textgraph 0.1.0"]


def test_init_creates_index_and_status_reports_counts(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [guide](docs/guide.md).\n")
    write(git_repo, "docs/guide.md", "ok\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    assert db_path(git_repo).is_file()
    capsys.readouterr()
    assert main(["--path", str(git_repo), "status"]) == 0
    out = capsys.readouterr().out
    assert "files: 2" in out
    assert "links: 1" in out
    assert "unresolved: 0" in out
    assert "last_sync:" in out


def test_init_refuses_when_index_already_exists(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "hello\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "init"]) == 1
    err = capsys.readouterr().err
    assert "sync" in err


def test_sync_without_init_fails(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--path", str(git_repo), "sync"]) == 1
    assert "init" in capsys.readouterr().err


def test_sync_indexes_new_and_deleted_files(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [guide](docs/guide.md).\n")
    write(git_repo, "docs/guide.md", "ok\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    write(git_repo, "notes.txt", "See [missing](./gone.md).\n")
    (git_repo / "docs" / "guide.md").unlink()
    assert main(["--path", str(git_repo), "sync"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "status"]) == 0
    out = capsys.readouterr().out
    assert "files: 2" in out
    # README.md is unchanged so its existing exact link is not re-resolved.
    assert "unresolved: 1" in out
    capsys.readouterr()
    assert main(["--path", str(git_repo), "sync", "--force"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "status"]) == 0
    assert "unresolved: 2" in capsys.readouterr().out


def test_sync_skips_unchanged_hashes(git_repo: Path, write) -> None:
    write(git_repo, "README.md", "See [guide](./guide.md).\n")
    write(git_repo, "guide.md", "ok\n")
    first = sync_index(git_repo, force=True)
    second = sync_index(git_repo, force=False)
    assert first.updated == 2
    assert second.updated == 0
    assert second.skipped == 2


def test_gitignore_files_are_not_indexed(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, ".gitignore", "secret.md\n")
    write(git_repo, "secret.md", "[x](./nope.md)\n")
    write(git_repo, "README.md", "hi\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "status"]) == 0
    out = capsys.readouterr().out
    assert "files: 1" in out
    assert "links: 0" in out


def test_version_does_not_touch_git_or_index(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.splitlines() == ["textgraph 0.1.0"]
    assert not (git_repo / INDEX_DIR).exists()


def test_indexes_default_text_extensions_and_skips_code(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "a.md", "md\n")
    write(git_repo, "b.mdc", "mdc\n")
    write(git_repo, "c.txt", "txt\n")
    write(git_repo, "d.rst", "rst\n")
    write(git_repo, "skip.py", "[x](./no.md)\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "status"]) == 0
    out = capsys.readouterr().out
    assert "files: 4" in out
    assert "links: 0" in out


def test_walks_up_to_git_root_from_subdirectory(
    git_repo: Path, write, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(git_repo, "README.md", "hi\n")
    nested = git_repo / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    assert main(["init"]) == 0
    assert db_path(git_repo).is_file()


def test_script_file_classification() -> None:
    assert is_script_file("tools/foo.py")
    assert is_script_file("src/app.ts")
    assert is_script_file("Justfile")
    assert is_script_file("path/Makefile")
    assert not is_script_file("README.md")
    assert not is_script_file("notes.txt")
    assert not is_text_file("foo.py")
    assert not is_text_file("justfile")
