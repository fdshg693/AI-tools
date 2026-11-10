from __future__ import annotations

import json
from pathlib import Path

import pytest

from textgraph.cli import main


@pytest.fixture
def linked_repo(git_repo: Path, write) -> Path:
    write(git_repo, "A.md", "See [b](B.md).\n")
    write(git_repo, "C.md", "See [b](./B.md).\n")
    write(git_repo, "B.md", "See [d](D.md) and [gone](./missing.md).\n")
    write(git_repo, "D.md", "leaf\n")
    write(git_repo, "docs/nested/deep.md", "nested\n")
    write(git_repo, "docs-extra.md", "extra\n")
    write(git_repo, "notes/unique-name.md", "unique\n")
    write(git_repo, "pkg/a/SKILL.md", "a\n")
    write(git_repo, "pkg/b/SKILL.md", "b\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    return git_repo


def test_files_lists_indexed_paths(linked_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    assert main(["--path", str(linked_repo), "files"]) == 0
    out = capsys.readouterr().out
    assert "A.md" in out
    assert "docs/nested/deep.md" in out
    assert "See [b]" not in out


def test_files_filter_is_string_prefix(
    linked_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert main(["--path", str(linked_repo), "files", "--filter", "docs"]) == 0
    out = capsys.readouterr().out
    assert "docs/nested/deep.md" in out
    assert "docs-extra.md" in out
    assert "\nA.md" not in out and not out.startswith("A.md")


def test_files_max_depth_collapses_human_tree(
    linked_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert main(["--path", str(linked_repo), "files", "--max-depth", "1"]) == 0
    lines = [
        line.split()[0]
        for line in capsys.readouterr().out.splitlines()
        if line and not line.startswith("path")
    ]
    assert "docs/" in lines
    assert "docs/nested/deep.md" not in lines
    assert "A.md" in lines


def test_files_json_is_flat_and_ignores_max_depth(
    linked_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert (
        main(
            [
                "--path",
                str(linked_repo),
                "files",
                "--json",
                "--max-depth",
                "1",
                "--filter",
                "docs",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload == ["docs-extra.md", "docs/nested/deep.md"]


def test_impact_inbound_then_outbound_one_hop(
    linked_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert main(["--path", str(linked_repo), "impact", "B.md"]) == 0
    out = capsys.readouterr().out
    inbound_at = out.index("inbound")
    outbound_at = out.index("outbound")
    unresolved_at = out.index("unresolved")
    assert inbound_at < outbound_at < unresolved_at
    inbound = out[inbound_at:outbound_at]
    outbound = out[outbound_at:unresolved_at]
    unresolved = out[unresolved_at:]
    assert "A.md" in inbound
    assert "C.md" in inbound
    assert "D.md" in outbound
    assert "missing.md" in unresolved
    assert "See [b]" not in out
    capsys.readouterr()
    assert main(["--path", str(linked_repo), "impact", "D.md"]) == 0
    d_out = capsys.readouterr().out
    assert "B.md" in d_out
    assert "A.md" not in d_out


def test_impact_accepts_absolute_and_unique_basename(
    linked_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert main(["--path", str(linked_repo), "impact", str(linked_repo / "B.md")]) == 0
    assert "target: B.md" in capsys.readouterr().out
    assert main(["--path", str(linked_repo), "impact", "unique-name.md"]) == 0
    assert "target: notes/unique-name.md" in capsys.readouterr().out


def test_impact_ambiguous_basename_lists_candidates(
    linked_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert main(["--path", str(linked_repo), "impact", "SKILL.md"]) == 1
    err = capsys.readouterr().err
    assert "ambiguous" in err
    assert "pkg/a/SKILL.md" in err
    assert "pkg/b/SKILL.md" in err


def test_impact_json_arrays(linked_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    assert main(["--path", str(linked_repo), "impact", "B.md", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["target"] == "B.md"
    assert [row["source"] for row in payload["inbound"]] == ["A.md", "C.md"]
    assert payload["outbound"][0]["resolved"] == "D.md"
    assert payload["unresolved"][0]["raw"] == "./missing.md"
    assert "text" not in payload["inbound"][0]


def test_impact_unknown_path_fails(linked_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    assert main(["--path", str(linked_repo), "impact", "no-such.md"]) == 1
    assert "not in index" in capsys.readouterr().err


def test_files_rejects_non_positive_max_depth(
    linked_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert main(["--path", str(linked_repo), "files", "--max-depth", "0"]) == 1
    assert "max-depth" in capsys.readouterr().err


def test_files_without_index_fails(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--path", str(git_repo), "files"]) == 1
    assert "init" in capsys.readouterr().err


def test_impact_stale_when_source_mtime_is_newer(
    linked_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(linked_repo, "A.md", "changed\n")
    capsys.readouterr()
    assert main(["--path", str(linked_repo), "impact", "B.md"]) == 1
    assert "sync" in capsys.readouterr().err


def test_files_stale_when_new_text_file_is_unindexed(
    linked_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(linked_repo, "E.md", "new\n")
    capsys.readouterr()
    assert main(["--path", str(linked_repo), "files"]) == 1
    assert "sync" in capsys.readouterr().err
