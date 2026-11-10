from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from textgraph.check import git_rename_destinations
from textgraph.cli import main


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        capture_output=True,
    )


def git_commit(root: Path, message: str, *, add_all: bool = True) -> None:
    if add_all:
        git(root, "add", "-A")
    git(
        root,
        "-c",
        "user.email=textgraph@example.com",
        "-c",
        "user.name=textgraph",
        "commit",
        "-m",
        message,
    )


def move_text(root: Path, src: str, dest: str) -> None:
    source = root.joinpath(*src.split("/"))
    target = root.joinpath(*dest.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    source.replace(target)


def test_check_reports_unresolved_and_ignores_urls(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(
        git_repo,
        "README.md",
        "See [web](https://example.com/gone.md) and [local](./missing.md).\n",
    )
    write(git_repo, "ok.md", "leaf\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "missing.md" in out
    assert "unresolved" in out
    assert "https://example.com" not in out


def test_check_clean_repo_exits_zero(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [ok](./ok.md).\n")
    write(git_repo, "ok.md", "leaf\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 0
    assert capsys.readouterr().out.strip() == "(none)"


def test_check_without_index_exits_two(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--path", str(git_repo), "check"]) == 2
    assert "init" in capsys.readouterr().err


def test_check_stale_index_exits_two(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "hi\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    write(git_repo, "new.md", "new\n")
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 2
    assert "sync" in capsys.readouterr().err


def test_check_suggests_unique_basename_after_move(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [unique](unique-name.md).\n")
    write(git_repo, "notes/unique-name.md", "unique\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    move_text(git_repo, "notes/unique-name.md", "other/unique-name.md")
    assert main(["--path", str(git_repo), "sync"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "unique-name.md" in out
    assert "other/unique-name.md" in out
    assert "unique-basename" in out
    assert "suggested" in out


def test_check_ambiguous_same_basename_is_not_rewritten(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [skill](SKILL.md).\n")
    write(git_repo, "pkg/a/SKILL.md", "a\n")
    write(git_repo, "pkg/b/SKILL.md", "b\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "ambiguous" in out
    assert "pkg/a/SKILL.md" in out
    assert "pkg/b/SKILL.md" in out
    capsys.readouterr()
    original = (git_repo / "README.md").read_text(encoding="utf-8")
    assert main(["--path", str(git_repo), "fix", "--apply"]) == 1
    assert (git_repo / "README.md").read_text(encoding="utf-8") == original
    err_out = capsys.readouterr().out
    assert "would apply" not in err_out
    assert "applied" not in err_out
    assert "skipped" in err_out


def test_fix_dry_run_does_not_write_unique_suffix(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [the guide](deep/file.md).\n")
    write(git_repo, "old/deep/file.md", "moved\n")
    write(git_repo, "other/file.md", "other\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    move_text(git_repo, "old/deep/file.md", "new/deep/file.md")
    assert main(["--path", str(git_repo), "sync"]) == 0
    original = (git_repo / "README.md").read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["--path", str(git_repo), "fix"]) == 1
    out = capsys.readouterr().out
    assert "would apply" in out
    assert "new/deep/file.md" in out
    assert "See [the guide]" in out
    assert (git_repo / "README.md").read_text(encoding="utf-8") == original


def test_fix_apply_rewrites_unique_suffix_and_keeps_link_text(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [the guide](deep/file.md).\n")
    write(git_repo, "old/deep/file.md", "moved\n")
    write(git_repo, "other/file.md", "other\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    move_text(git_repo, "old/deep/file.md", "new/deep/file.md")
    assert main(["--path", str(git_repo), "sync"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "fix", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "applied" in out
    text = (git_repo / "README.md").read_text(encoding="utf-8")
    assert text == "See [the guide](new/deep/file.md).\n"
    assert main(["--path", str(git_repo), "sync"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 0


def test_fix_does_not_apply_unique_basename(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [unique](unique-name.md).\n")
    write(git_repo, "notes/unique-name.md", "unique\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    move_text(git_repo, "notes/unique-name.md", "other/unique-name.md")
    assert main(["--path", str(git_repo), "sync"]) == 0
    original = (git_repo / "README.md").read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["--path", str(git_repo), "fix", "--apply"]) == 1
    assert (git_repo / "README.md").read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert "skipped" in out
    assert "unique-basename" in out
    assert "applied" not in out


def test_fix_apply_git_rename_when_basename_is_ambiguous(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [a](pkg/a/SKILL.md).\n")
    write(git_repo, "pkg/a/SKILL.md", "a\n")
    write(git_repo, "pkg/b/SKILL.md", "b\n")
    git_commit(git_repo, "initial")
    assert main(["--path", str(git_repo), "init"]) == 0
    (git_repo / "pkg" / "c").mkdir()
    git(git_repo, "mv", "pkg/a/SKILL.md", "pkg/c/SKILL.md")
    git_commit(git_repo, "rename skill", add_all=False)
    assert main(["--path", str(git_repo), "sync"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    check_out = capsys.readouterr().out
    assert "git-rename" in check_out
    assert "pkg/c/SKILL.md" in check_out
    assert main(["--path", str(git_repo), "fix", "--apply"]) == 0
    text = (git_repo / "README.md").read_text(encoding="utf-8")
    assert text == "See [a](pkg/c/SKILL.md).\n"


def test_fix_preserves_at_prefix(git_repo: Path, write, capsys: pytest.CaptureFixture[str]) -> None:
    write(git_repo, "docs/intro.md", "See @./deep/file.md\n")
    write(git_repo, "docs/old/deep/file.md", "moved\n")
    write(git_repo, "docs/other/file.md", "other\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    move_text(git_repo, "docs/old/deep/file.md", "docs/new/deep/file.md")
    assert main(["--path", str(git_repo), "sync"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "fix", "--apply"]) == 0
    text = (git_repo / "docs" / "intro.md").read_text(encoding="utf-8")
    assert text == "See @./new/deep/file.md\n"


def test_git_rename_skipped_without_git(tmp_path: Path) -> None:
    assert (
        git_rename_destinations(
            tmp_path,
            basename="file.md",
            old_path="old/file.md",
            current_files={"new/file.md"},
        )
        == []
    )


def test_fix_without_index_exits_two(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--path", str(git_repo), "fix"]) == 2
    assert "init" in capsys.readouterr().err


def test_check_ignores_script_links_without_scripts_flag(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "ok\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    write(git_repo, "tool.py", "# See [gone](./missing.md) and @./also-gone.md\n")
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 0
    assert capsys.readouterr().out.strip() == "(none)"
    assert main(["--path", str(git_repo), "files", "--json"]) == 0
    assert "tool.py" not in capsys.readouterr().out


def test_check_scripts_reports_markdown_and_at_links(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "ok\n")
    write(git_repo, "tool.py", "# See [gone](./missing.md)\n# also @./also-gone.md\n")
    write(git_repo, "justfile", "# [guide](./no-guide.md)\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check", "--scripts"]) == 1
    out = capsys.readouterr().out
    assert "tool.py" in out
    assert "missing.md" in out
    assert "also-gone.md" in out
    assert "justfile" in out
    assert "no-guide.md" in out
    capsys.readouterr()
    assert main(["--path", str(git_repo), "status"]) == 0
    status = capsys.readouterr().out
    assert "files: 1" in status
    assert "links: 0" in status


def test_check_scripts_does_not_require_comment_syntax(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "ok\n")
    write(git_repo, "tool.py", 'X = "[gone](./missing.md)"\n')
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check", "--scripts"]) == 1
    assert "missing.md" in capsys.readouterr().out


def test_check_scripts_clean_script_exits_zero(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [ok](./ok.md).\n")
    write(git_repo, "ok.md", "leaf\n")
    write(git_repo, "tool.py", "# See [ok](./ok.md) and @./README.md\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check", "--scripts"]) == 0
    assert capsys.readouterr().out.strip() == "(none)"


def test_fix_scripts_apply_git_rename(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "ok\n")
    write(git_repo, "tool.py", "# See [a](pkg/a/note.md) and @./pkg/a/note.md\n")
    write(git_repo, "pkg/a/note.md", "a\n")
    write(git_repo, "pkg/b/note.md", "b\n")
    git_commit(git_repo, "initial")
    assert main(["--path", str(git_repo), "init"]) == 0
    (git_repo / "pkg" / "c").mkdir()
    git(git_repo, "mv", "pkg/a/note.md", "pkg/c/note.md")
    git_commit(git_repo, "rename note", add_all=False)
    assert main(["--path", str(git_repo), "sync"]) == 0
    original = (git_repo / "tool.py").read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["--path", str(git_repo), "fix"]) == 0
    assert (git_repo / "tool.py").read_text(encoding="utf-8") == original
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check", "--scripts"]) == 1
    check_out = capsys.readouterr().out
    assert "git-rename" in check_out
    assert "pkg/c/note.md" in check_out
    assert main(["--path", str(git_repo), "fix", "--scripts", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "applied" in out
    text = (git_repo / "tool.py").read_text(encoding="utf-8")
    assert text == "# See [a](pkg/c/note.md) and @./pkg/c/note.md\n"
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check", "--scripts"]) == 0
