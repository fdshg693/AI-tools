from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from textgraph.cli import main


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def git_commit(root: Path, message: str) -> None:
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


def save_baseline(root: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> Path:
    capsys.readouterr()
    main(["--path", str(root), "check", "--json", *extra])
    path = root.parent / "before.json"
    path.write_text(capsys.readouterr().out, encoding="utf-8")
    return path


def check_baseline(
    root: Path, baseline: Path, capsys: pytest.CaptureFixture[str], *extra: str
) -> tuple[int, dict[str, object], str]:
    capsys.readouterr()
    code = main(["--path", str(root), "check", "--json", "--baseline", str(baseline), *extra])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def test_same_state_has_no_new_findings(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "[a](./missing.md)\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    baseline = save_baseline(git_repo, capsys)
    code, data, err = check_baseline(git_repo, baseline, capsys)
    assert code == 0
    assert data["findings"] == []
    assert "0 findings resolved" in err


def test_new_break_is_reported_once(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "[a](./missing.md)\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    baseline = save_baseline(git_repo, capsys)
    write(git_repo, "README.md", "[a](./missing.md)\n[b](./gone.md)\n")
    assert main(["--path", str(git_repo), "sync"]) == 0
    code, data, _err = check_baseline(git_repo, baseline, capsys)
    assert code == 1
    assert [f["raw"] for f in data["findings"]] == ["./gone.md"]


def test_table_output_lists_only_new(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "[a](./missing.md)\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    baseline = save_baseline(git_repo, capsys)
    write(git_repo, "README.md", "[a](./missing.md)\n[b](./gone.md)\n")
    assert main(["--path", str(git_repo), "sync"]) == 0
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check", "--baseline", str(baseline)]) == 1
    out = capsys.readouterr().out
    assert "./gone.md" in out
    assert "./missing.md" not in out


def test_duplicate_link_is_compared_by_count(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "[a](./missing.md)\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    baseline = save_baseline(git_repo, capsys)
    write(git_repo, "README.md", "[a](./missing.md)\n[a again](./missing.md)\n")
    assert main(["--path", str(git_repo), "sync"]) == 0
    code, data, _err = check_baseline(git_repo, baseline, capsys)
    assert code == 1
    assert [(f["raw"], f["line"]) for f in data["findings"]] == [("./missing.md", 2)]


def test_line_shift_is_not_new(git_repo: Path, write, capsys: pytest.CaptureFixture[str]) -> None:
    write(git_repo, "README.md", "[a](./missing.md)\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    baseline = save_baseline(git_repo, capsys)
    write(git_repo, "README.md", "# Title\n\nIntro.\n\n[a](./missing.md)\n")
    assert main(["--path", str(git_repo), "sync"]) == 0
    code, data, _err = check_baseline(git_repo, baseline, capsys)
    assert code == 0
    assert data["findings"] == []


def test_resolved_findings_are_counted(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "[a](./missing.md)\n[b](./gone.md)\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    baseline = save_baseline(git_repo, capsys)
    write(git_repo, "README.md", "[a](./missing.md)\n")
    assert main(["--path", str(git_repo), "sync"]) == 0
    code, data, err = check_baseline(git_repo, baseline, capsys)
    assert code == 0
    assert data["findings"] == []
    assert "1 findings resolved" in err


@pytest.mark.parametrize("commit", [False, True], ids=["staged", "committed"])
def test_git_mv_source_is_not_new(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str], commit: bool
) -> None:
    # I9: the moved file's finding keeps its key once the source is read as
    # its new path.
    write(git_repo, "docs/a.md", "[x](./missing.md)\n")
    git_commit(git_repo, "initial")
    assert main(["--path", str(git_repo), "init"]) == 0
    baseline = save_baseline(git_repo, capsys)
    (git_repo / "guide").mkdir()
    git(git_repo, "mv", "docs/a.md", "guide/a.md")
    if commit:
        git_commit(git_repo, "move")
    assert main(["--path", str(git_repo), "sync"]) == 0
    code, data, err = check_baseline(git_repo, baseline, capsys)
    assert code == 0
    assert data["findings"] == []
    assert "0 findings resolved" in err


def test_deleted_source_counts_as_resolved(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "hi\n")
    write(git_repo, "docs/a.md", "[x](./missing.md)\n")
    git_commit(git_repo, "initial")
    assert main(["--path", str(git_repo), "init"]) == 0
    baseline = save_baseline(git_repo, capsys)
    git(git_repo, "rm", "-q", "docs/a.md")
    assert main(["--path", str(git_repo), "sync"]) == 0
    code, data, err = check_baseline(git_repo, baseline, capsys)
    assert code == 0
    assert data["findings"] == []
    assert "1 findings resolved" in err


def test_hidden_external_is_not_resolved(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, ".gitignore", "build/\n")
    write(git_repo, "build/out.md", "generated\n")
    write(git_repo, "README.md", "[gen](build/out.md)\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    baseline = save_baseline(git_repo, capsys, "--external")
    code, data, err = check_baseline(git_repo, baseline, capsys)
    assert code == 0
    assert data["findings"] == []
    assert data["external"] == 1
    assert "0 findings resolved" in err


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", '{"external": 0}', '{"findings": [{"source": "a.md", "raw": "b.md"}]}'],
    ids=["text", "array", "no-findings", "missing-status"],
)
def test_broken_baseline_exits_two(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str], content: str
) -> None:
    write(git_repo, "README.md", "hi\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    baseline = git_repo.parent / "before.json"
    baseline.write_text(content, encoding="utf-8")
    capsys.readouterr()
    assert main(["--path", str(git_repo), "check", "--baseline", str(baseline)]) == 2
    assert "baseline" in capsys.readouterr().err


def test_missing_baseline_exits_two(
    git_repo: Path, write, capsys: pytest.CaptureFixture[str]
) -> None:
    write(git_repo, "README.md", "hi\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    capsys.readouterr()
    missing = git_repo.parent / "nope.json"
    assert main(["--path", str(git_repo), "check", "--baseline", str(missing)]) == 2
    assert "baseline" in capsys.readouterr().err


def test_fix_has_no_json_flag(git_repo: Path, write) -> None:
    write(git_repo, "README.md", "hi\n")
    assert main(["--path", str(git_repo), "init"]) == 0
    with pytest.raises(SystemExit):
        main(["--path", str(git_repo), "fix", "--json"])
