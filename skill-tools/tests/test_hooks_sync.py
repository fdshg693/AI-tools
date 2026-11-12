from __future__ import annotations

import json
from pathlib import Path

import pytest

from skill_tools.cli import main


@pytest.fixture
def env(tmp_path: Path, make_repo, make_hook_repo, hook_catalog, write_config):
    source = make_hook_repo(make_repo(tmp_path / "source"), hook_catalog)
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    return project, config


def _with_install(config: Path, body: str) -> None:
    config.write_text(config.read_text(encoding="utf-8") + body, encoding="utf-8")


def _sync(project: Path, config: Path, *argv: str) -> int:
    return main(["hooks", "sync", "--config", str(config), *argv], cwd=project)


def _managed(project: Path) -> set[tuple[str, str]]:
    manifest = json.loads((project / ".skill-tools" / "manifest.json").read_text("utf-8"))
    return {(entry["hookId"], entry["agent"]) for entry in manifest["hooks"]}


def test_sync_installs_listed_hooks_and_is_idempotent(env, capsys) -> None:
    project, config = env
    _with_install(config, "hooks:\n  install:\n    claude: [nested_rules]\n")

    assert _sync(project, config) == 0
    assert "install\tnested_rules\tclaude" in capsys.readouterr().out
    assert _managed(project) == {("nested_rules", "claude")}
    assert (project / ".claude" / "hooks" / "nested_rules.py").is_file()

    assert _sync(project, config) == 0
    assert "(no changes)" in capsys.readouterr().out


def test_sync_removes_managed_hooks_no_longer_listed(env, capsys) -> None:
    project, config = env
    original = config.read_text(encoding="utf-8")
    _with_install(config, "hooks:\n  install:\n    claude: [nested_rules]\n")
    assert _sync(project, config) == 0
    capsys.readouterr()

    config.write_text(original + "hooks:\n  install:\n    claude: []\n", encoding="utf-8")
    assert _sync(project, config, "--dry-run") == 0
    assert "would remove\tnested_rules\tclaude" in capsys.readouterr().out
    assert _managed(project) == {("nested_rules", "claude")}

    assert _sync(project, config) == 0
    assert _managed(project) == set()
    assert not (project / ".claude" / "hooks" / "nested_rules.py").exists()


def test_sync_without_install_list_is_a_config_error(env, capsys) -> None:
    project, config = env
    assert _sync(project, config) == 2
    assert "hooks.install is empty" in capsys.readouterr().err
