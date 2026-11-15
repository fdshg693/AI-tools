from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from textgraph.check import RenameDestinations, git_rename_destinations
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


def test_fix_does_not_apply_basename_only_git_rename(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    # B1: a rename of a different same-name file must not rewrite the link.
    # The destination shares the "docs" directory name, so I4 keeps it as a hint.
    write(git_repo, "README.md", "See [x](docs/index.md).\n")
    write(git_repo, "pkg/index.md", "pkg\n")
    write(git_repo, "keep/index.md", "keep\n")
    git_commit(git_repo, "initial")
    (git_repo / "docs" / "moved").mkdir(parents=True)
    git(git_repo, "mv", "pkg/index.md", "docs/moved/index.md")
    git_commit(git_repo, "rename unrelated index", add_all=False)
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    check_out = capsys.readouterr().out
    assert "git-rename-basename" in check_out
    assert "docs/moved/index.md" in check_out
    assert "suggested" in check_out
    assert main(["--path", str(git_repo), "fix", "--apply"]) == 1
    out = capsys.readouterr().out
    assert "applied" not in out
    assert "skipped" in out
    text = (git_repo / "README.md").read_text(encoding="utf-8")
    assert text == "See [x](docs/index.md).\n"


def test_check_drops_basename_rename_without_shared_directory(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    # I4: a same-name rename in an unrelated directory is not a candidate.
    write(git_repo, "README.md", "See [x](docs/index.md).\n")
    write(git_repo, "pkg/index.md", "pkg\n")
    write(git_repo, "keep/index.md", "keep\n")
    git_commit(git_repo, "initial")
    (git_repo / "moved").mkdir()
    git(git_repo, "mv", "pkg/index.md", "moved/index.md")
    git_commit(git_repo, "rename unrelated index", add_all=False)
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "unresolved" in out
    assert "moved/index.md" not in out
    assert "keep/index.md" not in out


def test_check_narrows_ambiguous_candidates_by_directory_name(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    # I4: only candidates sharing a directory name with the link are listed.
    write(
        git_repo,
        "README.md",
        "See [a](../tools/x/SKILL.md) and [b](../plugins/y/SKILL.md).\n",
    )
    write(git_repo, "plugins/a/SKILL.md", "a\n")
    write(git_repo, "plugins/b/SKILL.md", "b\n")
    write(git_repo, "other/c/SKILL.md", "c\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    lines = capsys.readouterr().out.splitlines()
    tools_line = next(line for line in lines if "../tools/x/SKILL.md" in line)
    plugins_line = next(line for line in lines if "../plugins/y/SKILL.md" in line)
    assert "unresolved" in tools_line
    assert "a/SKILL.md" not in tools_line
    assert "ambiguous" in plugins_line
    assert "plugins/a/SKILL.md" in plugins_line
    assert "plugins/b/SKILL.md" in plugins_line
    assert "other/c/SKILL.md" not in plugins_line


def test_check_reports_link_that_only_resolves_by_suffix(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    # B4: moving a file one level deeper breaks its "../" link, but the
    # resolver still finds the target by suffix. check must report it.
    write(git_repo, "tools/plugin/README.md", "See [doc](../_plugin/guide.md).\n")
    write(git_repo, "tools/_plugin/guide.md", "guide\n")
    write(git_repo, "tools/_plugin/other/guide.md", "other\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 0
    move_text(git_repo, "tools/plugin/README.md", "tools/plugin/deep/README.md")
    assert main(["--path", str(git_repo), "sync"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "suggested" in out
    assert "unique-suffix" in out
    assert "tools/_plugin/guide.md" in out
    assert main(["--path", str(git_repo), "fix", "--apply"]) == 0
    capsys.readouterr()
    text = (git_repo / "tools/plugin/deep/README.md").read_text(encoding="utf-8")
    assert text == "See [doc](../../_plugin/guide.md).\n"
    assert main(["--path", str(git_repo), "sync"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 0


def test_check_does_not_report_wiki_basename_resolution(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [[guide.md]].\n")
    write(git_repo, "notes/guide.md", "guide\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 0


def test_check_reports_markdown_basename_resolution(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [g](guide.md).\n")
    write(git_repo, "notes/guide.md", "guide\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "unique-basename" in out
    assert "notes/guide.md" in out


def test_check_accepts_directory_link_without_index_file(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    # B2: a directory with tracked files is a valid target without README.md.
    write(git_repo, "pkg/README.md", "See [skills](skills/) and [root](../).\n")
    write(git_repo, "pkg/skills/a/SKILL.md", "a\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 0


@pytest.mark.parametrize(
    "original",
    [
        b"# Title\r\n\r\nSee [a](./deep/file.md).\r\nTail line\r\n",
        b"# Title\n\r\nSee [a](./deep/file.md).\r\nTail\nlast-no-newline",
    ],
    ids=["crlf", "mixed"],
)
def test_fix_apply_keeps_line_endings(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str], original: bytes
) -> None:
    # B3: only the rewritten path changes; every other byte stays as-is.
    intro = git_repo / "docs" / "intro.md"
    intro.parent.mkdir(parents=True)
    intro.write_bytes(original)
    write(git_repo, "docs/old/deep/file.md", "moved\n")
    write(git_repo, "docs/other/file.md", "other\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    move_text(git_repo, "docs/old/deep/file.md", "docs/new/deep/file.md")
    assert main(["--path", str(git_repo), "sync"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "fix"]) == 1
    assert "./new/deep/file.md" in capsys.readouterr().out
    assert intro.read_bytes() == original
    assert main(["--path", str(git_repo), "fix", "--apply"]) == 0
    expected = original.replace(b"./deep/file.md", b"./new/deep/file.md")
    assert intro.read_bytes() == expected


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
        == RenameDestinations()
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


def _external_repo(git_repo: Path, write) -> None:
    """Links that are outside the index but exist on disk, plus one real break."""
    # A nested repository stands in for a submodule.
    sub = git_repo / "sub"
    sub.mkdir()
    git(sub, "init")
    write(sub, "doc.md", "nested\n")
    # A file next to the repository (an umbrella file seen from a submodule).
    write(git_repo.parent, "outside.md", "outside\n")
    # A gitignored generated file.
    write(git_repo, ".gitignore", "build/\n")
    write(git_repo, "build/out.md", "generated\n")
    write(
        git_repo,
        "docs/guide.md",
        "[sub](../sub/doc.md) [up](../../outside.md) [gen](../build/out.md)"
        " [dir](../sub) [gone](./missing.md)\n",
    )


def test_check_hides_links_that_exist_on_disk(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    _external_repo(git_repo, write)
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    captured = capsys.readouterr()
    assert "missing.md" in captured.out
    for raw in ("sub/doc.md", "outside.md", "build/out.md", "../sub "):
        assert raw not in captured.out
    # ``../sub`` is the nested repository's own path, which git lists, so it
    # resolves exactly and is not counted as external.
    assert "3 links point outside the index (exist on disk); use --external to list" in (
        captured.err
    )


def test_check_external_flag_lists_without_failing(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    _external_repo(git_repo, write)
    (git_repo / "docs" / "guide.md").write_text(
        "[sub](../sub/doc.md) [up](../../outside.md)\n", encoding="utf-8"
    )
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "(none)"
    assert "2 links point outside the index" in captured.err
    assert main(["--path", str(git_repo), "check", "--external"]) == 0
    captured = capsys.readouterr()
    assert "../sub/doc.md" in captured.out
    assert "../../outside.md" in captured.out
    assert "external" in captured.out
    assert "on-disk" in captured.out
    assert captured.err == ""


def test_fix_never_rewrites_external_links(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    # Same basename tracked elsewhere: without the on-disk check this would
    # be suggested as a unique-basename / suffix candidate.
    write(git_repo, "other/sub/doc.md", "tracked twin\n")
    _external_repo(git_repo, write)
    (git_repo / "docs" / "guide.md").write_text("[sub](../sub/doc.md)\n", encoding="utf-8")
    assert main(["--path", str(git_repo), "init"]) == 0
    original = (git_repo / "docs" / "guide.md").read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["--path", str(git_repo), "fix", "--apply"]) == 0
    assert (git_repo / "docs" / "guide.md").read_text(encoding="utf-8") == original
    assert main(["--path", str(git_repo), "fix", "--apply", "--external"]) == 0
    out = capsys.readouterr().out
    assert "applied" not in out
    assert "external" in out
    assert (git_repo / "docs" / "guide.md").read_text(encoding="utf-8") == original


def test_check_scripts_treats_on_disk_links_as_external(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "ok\n")
    write(git_repo.parent, "outside.md", "outside\n")
    write(git_repo, "tool.py", "# See [up](../outside.md) and [gone](./missing.md)\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check", "--scripts"]) == 1
    captured = capsys.readouterr()
    assert "missing.md" in captured.out
    assert "outside.md" not in captured.out
    assert "1 links point outside the index" in captured.err


def _count_git_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record every rename query (``git log`` / ``git diff``) made by textgraph."""
    calls: list[list[str]] = []
    original = subprocess.run

    def recording_run(args, *rest, **kwargs):
        if isinstance(args, list) and args[:1] == ["git"] and ({"log", "diff"} & set(args)):
            calls.append(list(args))
        return original(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    return calls


def test_check_uses_staged_git_mv(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    # I8: right after `git mv` (not committed yet) the rename is already known.
    write(git_repo, "README.md", "See [a](pkg/a/SKILL.md).\n")
    write(git_repo, "pkg/a/SKILL.md", "a\n")
    write(git_repo, "pkg/b/SKILL.md", "b\n")
    git_commit(git_repo, "initial")
    assert main(["--path", str(git_repo), "init"]) == 0
    (git_repo / "pkg" / "c").mkdir()
    git(git_repo, "mv", "pkg/a/SKILL.md", "pkg/c/SKILL.md")
    assert main(["--path", str(git_repo), "sync"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "git-rename" in out
    assert "git-rename-basename" not in out
    assert "pkg/c/SKILL.md" in out
    assert main(["--path", str(git_repo), "fix", "--apply"]) == 0
    text = (git_repo / "README.md").read_text(encoding="utf-8")
    assert text == "See [a](pkg/c/SKILL.md).\n"


def test_check_follows_rename_chain(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [a](pkg/a/SKILL.md).\n")
    write(git_repo, "pkg/a/SKILL.md", "a\n")
    write(git_repo, "pkg/other/SKILL.md", "other\n")
    git_commit(git_repo, "initial")
    assert main(["--path", str(git_repo), "init"]) == 0
    (git_repo / "pkg" / "b").mkdir()
    git(git_repo, "mv", "pkg/a/SKILL.md", "pkg/b/SKILL.md")
    git_commit(git_repo, "a to b", add_all=False)
    (git_repo / "pkg" / "c").mkdir()
    git(git_repo, "mv", "pkg/b/SKILL.md", "pkg/c/SKILL.md")
    git_commit(git_repo, "b to c", add_all=False)
    assert main(["--path", str(git_repo), "sync"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "git-rename" in out
    assert "pkg/c/SKILL.md" in out
    assert "pkg/b/SKILL.md" not in out
    assert main(["--path", str(git_repo), "fix", "--apply"]) == 0
    text = (git_repo / "README.md").read_text(encoding="utf-8")
    assert text == "See [a](pkg/c/SKILL.md).\n"


def test_rename_chain_ignores_older_rename_of_reused_path(git_repo: Path, write) -> None:
    # x/doc.md moved to y/doc.md long ago; later old/doc.md moved to x/doc.md
    # and then x/doc.md to z/doc.md. The old x→y rename is not part of the
    # chain from old/doc.md.
    write(git_repo, "x/doc.md", "first\n")
    write(git_repo, "old/doc.md", "second\n")
    git_commit(git_repo, "initial")
    (git_repo / "y").mkdir()
    git(git_repo, "mv", "x/doc.md", "y/doc.md")
    git_commit(git_repo, "x to y", add_all=False)
    git(git_repo, "mv", "old/doc.md", "x/doc.md")
    git_commit(git_repo, "old to x", add_all=False)
    (git_repo / "z").mkdir()
    git(git_repo, "mv", "x/doc.md", "z/doc.md")
    git_commit(git_repo, "x to z", add_all=False)
    found = git_rename_destinations(
        git_repo,
        basename="doc.md",
        old_path="old/doc.md",
        current_files={"y/doc.md", "z/doc.md"},
    )
    assert found == RenameDestinations(exact=("z/doc.md",))


def test_check_does_not_call_git_without_broken_links(
    git_repo: Path, write, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [g](docs/guide.md).\n")
    write(git_repo, "docs/guide.md", "guide\n")
    git_commit(git_repo, "initial")
    assert main(["--path", str(git_repo), "init"]) == 0
    calls = _count_git_calls(monkeypatch)
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 0
    assert calls == []


def test_check_reads_rename_history_once(
    git_repo: Path, write, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write(
        git_repo,
        "README.md",
        "[a](pkg/a/one.md) [b](pkg/a/two.md) [c](pkg/a/three.md) [d](gone/four.md)\n",
    )
    for name in ("one", "two", "three"):
        write(git_repo, f"pkg/a/{name}.md", f"{name}\n")
    git_commit(git_repo, "initial")
    assert main(["--path", str(git_repo), "init"]) == 0
    git(git_repo, "mv", "pkg/a", "pkg/moved")
    git_commit(git_repo, "move a", add_all=False)
    assert main(["--path", str(git_repo), "sync"]) == 0
    calls = _count_git_calls(monkeypatch)
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    assert len([call for call in calls if "log" in call]) == 1
    assert len([call for call in calls if "diff" in call]) == 1


def test_check_git_rename_with_non_ascii_path(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "See [m](docs/a/メモ.md).\n")
    write(git_repo, "docs/a/メモ.md", "memo\n")
    write(git_repo, "docs/b/メモ.md", "other\n")
    git_commit(git_repo, "initial")
    assert main(["--path", str(git_repo), "init"]) == 0
    (git_repo / "docs" / "c").mkdir()
    git(git_repo, "mv", "docs/a/メモ.md", "docs/c/メモ.md")
    git_commit(git_repo, "rename memo", add_all=False)
    assert main(["--path", str(git_repo), "sync"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "git-rename" in out
    assert "docs/c/メモ.md" in out


def test_excluded_files_are_not_indexed_nor_stale(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, ".textgraph.toml", 'exclude = ["output/**"]\n')
    write(git_repo, "README.md", "See [page](output/page.md).\n")
    write(git_repo, "output/page.md", "[gone](/site/absolute/path.md)\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "files", "--json"]) == 0
    assert "output/page.md" not in capsys.readouterr().out
    # The link to the excluded file still resolves, and the excluded file's
    # own broken link is not reported.
    assert main(["--path", str(git_repo), "check"]) == 0
    assert capsys.readouterr().out.strip() == "(none)"
    # A new excluded file does not make the index stale.
    write(git_repo, "output/new.md", "new\n")
    assert main(["--path", str(git_repo), "check"]) == 0


def test_widening_exclude_makes_index_stale(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "ok\n")
    write(git_repo, "output/page.md", "page\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    write(git_repo, ".textgraph.toml", 'exclude = ["output/**"]\n')
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 2
    assert "sync" in capsys.readouterr().err
    assert main(["--path", str(git_repo), "sync"]) == 0
    assert "removed 1" in capsys.readouterr().out
    assert main(["--path", str(git_repo), "check"]) == 0


def test_check_scripts_skips_template_fragments(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "ok\n")
    write(
        git_repo,
        "tool.py",
        'A = f"[x]({name}.md)"\n'
        'B = "[x]($HOME/a.md)"\n'
        'C = "[x](docs/*.md)"\n'
        'D = "[x](./real-missing.md)"\n',
    )
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check", "--scripts"]) == 1
    out = capsys.readouterr().out
    assert "real-missing.md" in out
    assert "{name}" not in out
    assert "$HOME" not in out
    assert "*.md" not in out


def test_document_template_links_are_still_reported(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "[x]({var}.md)\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check"]) == 1
    assert "{var}.md" in capsys.readouterr().out


def test_scripts_exclude_only_limits_the_script_scan(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, ".textgraph.toml", 'scripts_exclude = ["**/tests/**"]\n')
    write(git_repo, "README.md", "ok\n")
    write(git_repo, "pkg/tests/test_a.py", "# [fixture](./missing-fixture.md)\n")
    write(git_repo, "pkg/tests/notes.md", "[gone](./missing-note.md)\n")
    write(git_repo, "pkg/tool.py", "# [gone](./missing-tool.md)\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check", "--scripts"]) == 1
    out = capsys.readouterr().out
    assert "missing-fixture.md" not in out
    assert "missing-tool.md" in out
    # Documents under tests/ are still indexed and checked.
    assert "missing-note.md" in out
