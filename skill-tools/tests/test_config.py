from __future__ import annotations

from pathlib import Path

import pytest

from skill_tools.config import (
    apply_cli_overrides,
    default_index_path,
    initialize_user_config,
    load_config,
    user_config_path,
)
from skill_tools.models import ConfigError, SourceError


def test_config_priority_and_relative_index_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd_config = tmp_path / "skill-tools.yaml"
    cwd_config.write_text(
        "source:\n  type: local\n  path: ./source\nindex:\n  path: cache/index.json\n",
        encoding="utf-8",
    )
    config = load_config(cwd=tmp_path)
    assert config.source.type == "local"
    assert config.source.path == (tmp_path / "source").resolve()
    assert config.index.path == (tmp_path / "cache/index.json").resolve()

    explicit = tmp_path / "explicit.yaml"
    explicit.write_text(
        "source:\n  type: github\n  owner: somebody\n  repository: skills\n  ref: v1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SKILL_TOOLS_CONFIG", str(explicit))
    assert load_config(cwd=tmp_path).source.owner == "somebody"


@pytest.mark.parametrize(
    "text",
    [
        "source:\n  type: local\n  path: ''\n",
        "index:\n  other: value\n",
        "skills:\n  id:\n    destination: ../outside\n",
    ],
)
def test_invalid_config_is_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / "skill-tools.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(config_path=path)


def test_targets_and_target_specific_skill_destinations(tmp_path: Path) -> None:
    path = tmp_path / "skill-tools.yaml"
    path.write_text(
        "targets:\n  claude:\n    destination: .claude/skills\n"
        "  agents:\n    destination: .agents/skills\n"
        "skills:\n  example/SKILL.md:\n    destination: legacy\n"
        "    destinations:\n      agents: custom-agents\n",
        encoding="utf-8",
    )

    config = load_config(config_path=path)

    assert config.targets == {
        "claude": ".claude/skills",
        "agents": ".agents/skills",
    }
    assert config.destination_for("example/SKILL.md") == "legacy"
    assert config.destination_for("example/SKILL.md", "claude") == ".claude/skills"
    assert config.destination_for("example/SKILL.md", "agents") == "custom-agents"


@pytest.mark.parametrize(
    "text",
    [
        "targets:\n  bad/name:\n    destination: skills\n",
        "targets:\n  bad:\n    destination: ../outside\n",
        "skills:\n  id:\n    destination: safe\n    destinations:\n      bad: ../outside\n",
    ],
)
def test_invalid_targets_are_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / "skill-tools.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(config_path=path)


def test_default_cache_paths_are_platform_specific(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKILL_TOOLS_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
    assert default_index_path().as_posix().endswith("skill-tools/skill-index.json")
    assert user_config_path().as_posix().endswith("skill-tools/skill-tools.yaml")


def test_cli_overrides_replace_source_and_index(tmp_path: Path) -> None:
    config = load_config(cwd=tmp_path)
    local_root = tmp_path / "clone"
    local_root.mkdir()
    updated = apply_cli_overrides(
        config,
        source_type="local",
        repo=local_root,
        index_path=Path("idx.json"),
        cwd=tmp_path,
    )
    assert updated.source.type == "local"
    assert updated.source.path == local_root.resolve()
    assert updated.index.path == (tmp_path / "idx.json").resolve()
    with pytest.raises(SourceError, match="--repo is required"):
        apply_cli_overrides(config, source_type="local")


def test_global_and_cwd_configs_are_merged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    global_source = tmp_path / "global-source"
    cwd_source = tmp_path / "cwd-source"
    global_path = user_config_path()
    global_path.parent.mkdir(parents=True)
    global_path.write_text(
        f"source:\n  type: local\n  path: {global_source.as_posix()}\n"
        "skills:\n  shared/SKILL.md:\n    destination: global-destination\n",
        encoding="utf-8",
    )
    cwd = tmp_path / "project"
    cwd.mkdir()
    (cwd / "skill-tools.yaml").write_text(
        f"source:\n  path: {cwd_source.as_posix()}\n"
        "skills:\n  local/SKILL.md:\n    destination: cwd-destination\n",
        encoding="utf-8",
    )

    config = load_config(cwd=cwd)

    assert config.source.path == cwd_source.resolve()
    assert config.destinations == {
        "shared/SKILL.md": "global-destination",
        "local/SKILL.md": "cwd-destination",
    }
    assert config.global_config_path == global_path
    assert config.cwd_config_path == cwd / "skill-tools.yaml"
    assert config.global_config_exists


def test_missing_global_config_is_reported_by_config_show(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    from skill_tools.cli import main

    assert main(["config", "show"], cwd=tmp_path) == 0
    captured = capsys.readouterr()
    assert "missing; using embedded defaults" in captured.out
    assert "package.pyproject:" in captured.out
    assert "global config is missing" in captured.err


def test_initialize_user_config_writes_explicit_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    path, created = initialize_user_config()

    assert created
    text = path.read_text(encoding="utf-8")
    assert "owner: fdshg693" in text
    assert "repository: ai" in text
    assert "ref: main" in text
    assert "path:" in text
    assert "fb:" in text
    assert initialize_user_config() == (path, False)


def test_fb_path_is_resolved_relative_to_the_config_file(tmp_path: Path) -> None:
    path = tmp_path / "skill-tools.yaml"
    path.write_text("fb:\n  path: nested/fb\n", encoding="utf-8")

    config = load_config(config_path=path)

    assert config.fb.path == (tmp_path / "nested" / "fb").resolve()


def test_default_fb_path_uses_the_checkout_when_pyproject_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SKILL_TOOLS_FB_DIR", raising=False)
    checkout = tmp_path / "checkout"
    monkeypatch.setattr("skill_tools.config.project_root", lambda: checkout)
    monkeypatch.setattr("skill_tools.config.pyproject_path", lambda: checkout / "pyproject.toml")

    config = load_config(cwd=tmp_path / "work")

    assert config.fb.path == checkout / "fb"


def test_default_fb_path_uses_the_cache_without_a_shipped_pyproject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SKILL_TOOLS_FB_DIR", raising=False)
    monkeypatch.setenv("SKILL_TOOLS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("skill_tools.config.pyproject_path", lambda: None)

    config = load_config(cwd=tmp_path / "work")

    assert config.fb.path == (tmp_path / "home" / "fb").resolve()


def test_fb_rejects_unknown_keys_and_invalid_paths(tmp_path: Path) -> None:
    unknown = tmp_path / "unknown.yaml"
    unknown.write_text("fb:\n  other: value\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="fb contains unknown keys"):
        load_config(config_path=unknown)

    for text in ("fb:\n  path: ''\n", "fb:\n  path: 1\n", "fb: []\n"):
        path = tmp_path / "invalid.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ConfigError, match="fb"):
            load_config(config_path=path)


def test_hooks_section_sets_default_agents_destinations_and_settings_file(tmp_path: Path) -> None:
    path = tmp_path / "explicit.yaml"
    path.write_text(
        "hooks:\n"
        "  default_agents: [claude, codex]\n"
        "  agents:\n"
        "    claude:\n"
        "      settings_file: local\n"
        "    codex:\n"
        "      destination: tools/codex-hooks\n",
        encoding="utf-8",
    )

    hooks = load_config(config_path=path).hooks

    assert hooks.default_agents == ("claude", "codex")
    assert hooks.claude_settings_file == "local"
    assert hooks.destinations == {"codex": "tools/codex-hooks"}


@pytest.mark.parametrize(
    "text",
    [
        "hooks:\n  default_agents: [cline]\n",
        "hooks:\n  default_agents: claude\n",
        "hooks:\n  extra: 1\n",
        "hooks:\n  agents:\n    cline: {}\n",
        "hooks:\n  agents:\n    codex:\n      settings_file: local\n",
        "hooks:\n  agents:\n    claude:\n      settings_file: user\n",
        "hooks:\n  agents:\n    claude:\n      destination: ../outside\n",
        "hooks:\n  agents:\n    claude:\n      destination: .skill-tools/hooks\n",
    ],
)
def test_invalid_hooks_section_is_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / "explicit.yaml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(config_path=path)
