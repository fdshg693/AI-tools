from __future__ import annotations

from pathlib import Path

import pytest

from agents_rules.cli import main, tool_version


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("root rules\n", encoding="utf-8")
    (tmp_path / "tools" / "foo").mkdir(parents=True)
    (tmp_path / "tools" / "foo" / "AGENTS.md").write_text("foo rules\n\n", encoding="utf-8")
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "AGENTS.md").write_text("ignored\n", encoding="utf-8")
    return tmp_path


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out == f"agents-rules {tool_version()}\n"


def test_all_generates_three_targets(repo: Path) -> None:
    assert main(["--repo-root", str(repo), "-q"]) == 0

    assert read(repo / ".clinerules" / "root.md") == '---\npaths:\n  - "**"\n---\n\nroot rules\n'
    assert read(repo / ".clinerules" / "tools-foo.md") == (
        '---\npaths:\n  - "tools/foo/**"\n---\n\nfoo rules\n'
    )
    assert read(repo / ".github" / "instructions" / "tools-foo.instructions.md") == (
        '---\nname: "tools/foo instructions"\n'
        'description: "Instructions for files in tools/foo/"\n'
        'applyTo: "tools/foo/**"\n---\n\nfoo rules\n'
    )
    assert read(repo / ".agents" / "rules" / "root.md") == (
        "---\ntrigger: always_on\nglob:\ndescription:\n---\n\nroot rules\n"
    )
    assert read(repo / ".agents" / "rules" / "tools-foo.md") == (
        "---\ntrigger: glob\nglob: tools/foo/**\ndescription:\n---\n\nfoo rules\n"
    )
    assert not (repo / ".cursor").exists()
    assert not (repo / ".clinerules" / "node_modules-x.md").exists()


def test_cursor_is_opt_in(repo: Path) -> None:
    assert main(["--repo-root", str(repo), "-t", "cursor", "-q"]) == 0
    assert read(repo / ".cursor" / "rules" / "tools-foo.mdc") == (
        '---\nglobs: "tools/foo/**"\nalwaysApply: false\n---\n\nfoo rules\n'
    )
    assert not (repo / ".clinerules").exists()


def test_output_dir_from_ai_tools_yaml(repo: Path) -> None:
    (repo / "ai-tools.yaml").write_text(
        "tools:\n  cline:\n    rules_from_agents_md:\n      output_dir: custom/cline\n",
        encoding="utf-8",
    )
    assert main(["--repo-root", str(repo), "-t", "cline", "-q"]) == 0
    assert (repo / "custom" / "cline" / "root.md").is_file()


def test_output_dir_requires_single_target(repo: Path, tmp_path: Path) -> None:
    assert main(["--repo-root", str(repo), "--output-dir", str(tmp_path / "o")]) == 2
    assert main(["--repo-root", str(repo), "-t", "cline", "--output-dir", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / "tools-foo.md").is_file()


def test_dry_run_and_check_do_not_write(repo: Path) -> None:
    assert main(["--repo-root", str(repo), "--dry-run"]) == 0
    assert main(["--repo-root", str(repo), "--check"]) == 1
    assert not (repo / ".clinerules").exists()

    assert main(["--repo-root", str(repo), "-q"]) == 0
    assert main(["--repo-root", str(repo), "--check"]) == 0


def test_exclude(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--repo-root", str(repo), "--list-sources", "-x", "tools/*"]) == 0
    assert capsys.readouterr().out == "AGENTS.md\n"


def test_repo_root_discovered_from_cwd(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo / "tools" / "foo")
    assert main(["-t", "cline", "-q"]) == 0
    assert (repo / ".clinerules" / "tools-foo.md").is_file()
