"""Top-level `skill-tools --fb` saves one file per feedback item."""

from __future__ import annotations

import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from skill_tools.cli import main

FIXED_NOW = datetime(2026, 9, 13, 12, 34, 56, tzinfo=timezone.utc)

WORKFLOW = """\
version: 1
workflows:
  - id: sample-flow
    title: Sample
    purpose: Exercise feedback lookup
    steps:
      - id: read
        skill: plugins/one/skills/alpha/SKILL.md
"""


class _FrozenDateTime:
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW


def _freeze_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("skill_tools.feedback.datetime", _FrozenDateTime)


def _prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_repo, write_config
) -> tuple[Path, Path, Path]:
    source = make_repo(tmp_path / "source")
    (source / "repo-workflows.yaml").write_text(WORKFLOW, encoding="utf-8")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    fb_dir = tmp_path / "fb"
    monkeypatch.setenv("SKILL_TOOLS_FB_DIR", str(fb_dir))
    _freeze_now(monkeypatch)
    return source, config, fb_dir


def _saved(fb_dir: Path) -> Path:
    files = list(fb_dir.rglob("*-fb.md"))
    assert len(files) == 1
    return files[0]


def test_skill_name_saves_body_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, make_repo, write_config
) -> None:
    _source, config, fb_dir = _prepare(tmp_path, monkeypatch, make_repo, write_config)
    body = "  leading\nstill here\n"

    code = main(
        ["--config", str(config), "--fb", "alpha", "--fb-text", body],
        cwd=tmp_path,
    )

    assert code == 0
    saved = Path(capsys.readouterr().out.strip())
    assert saved == (fb_dir / "skills" / "alpha" / "20260913-123456-fb.md").resolve()
    assert saved.read_text(encoding="utf-8") == body


def test_tool_and_workflow_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, make_repo, write_config
) -> None:
    source, config, fb_dir = _prepare(tmp_path, monkeypatch, make_repo, write_config)

    assert (
        main(
            ["--config", str(config), "--fb", "tools/alpha-tool", "--fb-text", "tool body"],
            cwd=tmp_path,
        )
        == 0
    )
    tool_path = Path(capsys.readouterr().out.strip())
    assert tool_path.parent == fb_dir / "tools" / "alpha-tool"
    assert tool_path.read_text(encoding="utf-8") == "tool body"

    assert (
        main(
            ["--config", str(config), "--fb", "sample-flow", "--fb-text", "flow body"],
            cwd=tmp_path,
        )
        == 0
    )
    flow_path = Path(capsys.readouterr().out.strip())
    assert flow_path.parent == fb_dir / "workflows" / "sample-flow"
    assert flow_path.read_text(encoding="utf-8") == "flow body"
    assert source.is_dir()


def test_fb_kind_selects_one_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, make_repo, write_config
) -> None:
    source, config, fb_dir = _prepare(tmp_path, monkeypatch, make_repo, write_config)
    _add_tool_named_alpha(source)

    code = main(
        [
            "--config",
            str(config),
            "--fb",
            "plugins/one/skills/alpha/SKILL.md",
            "--fb-kind",
            "skill",
            "--fb-text",
            "by id",
        ],
        cwd=tmp_path,
    )

    assert code == 0
    saved = Path(capsys.readouterr().out.strip())
    assert saved.parent == fb_dir / "skills" / "alpha"
    assert saved.read_text(encoding="utf-8") == "by id"


def test_ambiguous_skill_and_tool_does_not_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, make_repo, write_config
) -> None:
    source, config, fb_dir = _prepare(tmp_path, monkeypatch, make_repo, write_config)
    _add_tool_named_alpha(source)

    code = main(
        ["--config", str(config), "--fb", "alpha", "--fb-text", "nope"],
        cwd=tmp_path,
    )

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "skill: plugins/one/skills/alpha/SKILL.md" in captured.err
    assert "tool: alpha" in captured.err
    assert "--fb-kind" in captured.err
    assert not fb_dir.exists()


def test_unknown_name_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, make_repo, write_config
) -> None:
    _source, config, fb_dir = _prepare(tmp_path, monkeypatch, make_repo, write_config)

    code = main(
        ["--config", str(config), "--fb", "missing-name", "--fb-text", "nope"],
        cwd=tmp_path,
    )

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "list-skills" in captured.err
    assert not fb_dir.exists()


def test_stdin_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, make_repo, write_config
) -> None:
    _source, config, fb_dir = _prepare(tmp_path, monkeypatch, make_repo, write_config)
    stdin = io.StringIO("from stdin\n")
    monkeypatch.setattr(stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys, "stdin", stdin)

    code = main(["--config", str(config), "--fb", "alpha"], cwd=tmp_path)

    assert code == 0
    saved = Path(capsys.readouterr().out.strip())
    assert saved.read_text(encoding="utf-8") == "from stdin\n"
    assert saved.parent == fb_dir / "skills" / "alpha"


def test_empty_body_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, make_repo, write_config
) -> None:
    _source, config, fb_dir = _prepare(tmp_path, monkeypatch, make_repo, write_config)

    assert main(["--config", str(config), "--fb", "alpha", "--fb-text", ""], cwd=tmp_path) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "empty" in captured.err
    assert not fb_dir.exists()

    stdin = io.StringIO("")
    monkeypatch.setattr(stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys, "stdin", stdin)
    assert main(["--config", str(config), "--fb", "alpha"], cwd=tmp_path) == 1
    assert not fb_dir.exists()


def test_same_second_collision_adds_suffix_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, make_repo, write_config
) -> None:
    _source, config, fb_dir = _prepare(tmp_path, monkeypatch, make_repo, write_config)

    assert main(["--config", str(config), "--fb", "alpha", "--fb-text", "one"], cwd=tmp_path) == 0
    first = Path(capsys.readouterr().out.strip())
    assert main(["--config", str(config), "--fb", "alpha", "--fb-text", "two"], cwd=tmp_path) == 0
    second = Path(capsys.readouterr().out.strip())

    assert first.name == "20260913-123456-fb.md"
    assert second.name == "20260913-123456-2-fb.md"
    assert first.read_text(encoding="utf-8") == "one"
    assert second.read_text(encoding="utf-8") == "two"


def test_fb_root_priority_is_env_then_config_then_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    (source / "repo-workflows.yaml").write_text(WORKFLOW, encoding="utf-8")
    _freeze_now(monkeypatch)
    default_root = tmp_path / "default-fb"
    monkeypatch.setattr("skill_tools.config.default_fb_path", lambda: default_root)

    config = tmp_path / "cfg.yaml"
    write_config(config, source, tmp_path / "index.json")
    config.write_text(
        config.read_text(encoding="utf-8") + "fb:\n  path: relative-fb\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SKILL_TOOLS_FB_DIR", str(tmp_path / "from-env"))
    assert main(["--config", str(config), "--fb", "alpha", "--fb-text", "env"], cwd=tmp_path) == 0
    env_saved = Path(capsys.readouterr().out.strip())
    assert env_saved.parent == tmp_path / "from-env" / "skills" / "alpha"

    monkeypatch.delenv("SKILL_TOOLS_FB_DIR")
    assert (
        main(["--config", str(config), "--fb", "alpha", "--fb-text", "configured"], cwd=tmp_path)
        == 0
    )
    configured = Path(capsys.readouterr().out.strip())
    assert configured.parent == (tmp_path / "relative-fb" / "skills" / "alpha").resolve()

    bare = tmp_path / "bare.yaml"
    write_config(bare, source, tmp_path / "index.json")
    assert main(["--config", str(bare), "--fb", "alpha", "--fb-text", "default"], cwd=tmp_path) == 0
    default_saved = Path(capsys.readouterr().out.strip())
    assert default_saved.parent == default_root / "skills" / "alpha"


def test_unsafe_resolved_name_is_not_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, make_repo, write_config
) -> None:
    source, config, fb_dir = _prepare(tmp_path, monkeypatch, make_repo, write_config)
    escape = source / "plugins" / "one" / "skills" / "escape"
    escape.mkdir(parents=True)
    (escape / "SKILL.md").write_text(
        "---\nname: ../escape\ndescription: unsafe name\n---\n\n# escape\n",
        encoding="utf-8",
    )

    code = main(
        ["--config", str(config), "--fb", "../escape", "--fb-text", "nope"],
        cwd=tmp_path,
    )

    assert code == 2
    assert capsys.readouterr().out == ""
    assert not fb_dir.exists()
    assert not (tmp_path / "escape").exists()


def test_broken_workflows_file_still_saves_skill_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, make_repo, write_config
) -> None:
    source, config, fb_dir = _prepare(tmp_path, monkeypatch, make_repo, write_config)
    (source / "repo-workflows.yaml").write_text("workflows: [\n", encoding="utf-8")

    code = main(
        ["--config", str(config), "--fb", "alpha", "--fb-text", "still saved"],
        cwd=tmp_path,
    )

    assert code == 0
    saved = Path(capsys.readouterr().out.strip())
    assert saved.parent == fb_dir / "skills" / "alpha"
    assert saved.read_text(encoding="utf-8") == "still saved"


def _add_tool_named_alpha(source: Path) -> None:
    tool_dir = source / "tools" / "alpha"
    tool_dir.mkdir(parents=True)
    (tool_dir / "pyproject.toml").write_text(
        '[project]\nname = "alpha"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    catalog = source / "repo-tools.yaml"
    catalog.write_text(
        catalog.read_text(encoding="utf-8")
        + '  alpha:\n    path: tools/alpha\n    install: "echo alpha"\n',
        encoding="utf-8",
    )
