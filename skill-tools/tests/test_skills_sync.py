from __future__ import annotations

import json
from pathlib import Path

import pytest

from skill_tools.cli import main

ALPHA = "plugins/one/skills/alpha/SKILL.md"
BETA = "plugins/two/beta/SKILL.md"


@pytest.fixture
def env(tmp_path: Path, make_repo, write_config):
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    return project, config, config.read_text(encoding="utf-8")


def _set_list(config: Path, original: str, body: str) -> None:
    config.write_text(original + body, encoding="utf-8")


def _sync(project: Path, config: Path, *argv: str) -> int:
    return main(["sync-skills", "--config", str(config), *argv], cwd=project)


def _managed(project: Path) -> set[str]:
    path = project / ".skill-tools" / "manifest.json"
    if not path.exists():
        return set()
    return {entry["canonicalId"] for entry in json.loads(path.read_text("utf-8"))["entries"]}


def test_sync_installs_listed_skills_and_is_idempotent(env, capsys) -> None:
    project, config, original = env
    _set_list(config, original, "install_skills: [alpha, plugins/two/beta/SKILL.md]\n")

    assert _sync(project, config, "--dry-run") == 0
    assert capsys.readouterr().out.count("would install") == 2
    assert _managed(project) == set()

    assert _sync(project, config) == 0
    assert _managed(project) == {ALPHA, BETA}
    assert (project / ".claude" / "skills" / "alpha" / "SKILL.md").is_file()
    capsys.readouterr()

    assert _sync(project, config) == 0
    assert "(no changes)" in capsys.readouterr().out


def test_sync_expands_self(env) -> None:
    project, config, original = env
    _set_list(config, original, f"self_skill: {ALPHA}\ninstall_skills: [self]\n")
    assert _sync(project, config) == 0
    assert _managed(project) == {ALPHA}


def test_sync_removes_managed_skills_no_longer_listed(env, capsys) -> None:
    project, config, original = env
    _set_list(config, original, "install_skills: [alpha, beta]\n")
    assert _sync(project, config) == 0
    capsys.readouterr()

    _set_list(config, original, "install_skills: [alpha]\n")
    assert _sync(project, config, "--dry-run") == 0
    assert f"would remove\t{BETA}" in capsys.readouterr().out
    assert _managed(project) == {ALPHA, BETA}

    assert _sync(project, config) == 0
    assert _managed(project) == {ALPHA}
    assert not (project / ".claude" / "skills" / "beta").exists()


def test_sync_keeps_unmanaged_skills(env) -> None:
    project, config, original = env
    manual = project / ".claude" / "skills" / "manual"
    manual.mkdir(parents=True)
    (manual / "SKILL.md").write_text("hand placed\n", encoding="utf-8")
    _set_list(config, original, "install_skills: [alpha]\n")
    assert _sync(project, config) == 0
    assert (manual / "SKILL.md").is_file()


def test_sync_stops_on_drift_before_changing_anything(env, capsys) -> None:
    project, config, original = env
    _set_list(config, original, "install_skills: [beta]\n")
    assert _sync(project, config) == 0
    (project / ".claude" / "skills" / "beta" / "SKILL.md").write_text("edited\n", "utf-8")

    _set_list(config, original, "install_skills: [alpha]\n")
    assert _sync(project, config) == 4
    assert "drifted" in capsys.readouterr().err
    assert _managed(project) == {BETA}
    assert not (project / ".claude" / "skills" / "alpha").exists()

    assert _sync(project, config, "--force") == 0
    assert _managed(project) == {ALPHA}


def test_sync_refuses_an_existing_unmanaged_destination_without_overwrite(env) -> None:
    project, config, original = env
    existing = project / ".claude" / "skills" / "alpha"
    existing.mkdir(parents=True)
    _set_list(config, original, "install_skills: [alpha]\n")
    assert _sync(project, config) == 4
    assert _managed(project) == set()
    assert _sync(project, config, "--overwrite") == 0
    assert _managed(project) == {ALPHA}


def test_sync_without_install_list_is_a_config_error(env, capsys) -> None:
    project, config, original = env
    assert _sync(project, config) == 2
    assert "install_skills is empty" in capsys.readouterr().err
    _set_list(config, original, "install_skills: []\n")
    assert _sync(project, config) == 2


def test_sync_rejects_an_unknown_skill(env, capsys) -> None:
    project, config, original = env
    _set_list(config, original, "install_skills: [alpha, nope]\n")
    assert _sync(project, config) == 2
    assert _managed(project) == set()


@pytest.mark.parametrize("value", ["alpha", "[1]", "['']"])
def test_install_skills_must_be_a_list_of_selectors(env, value) -> None:
    project, config, original = env
    _set_list(config, original, f"install_skills: {value}\n")
    assert _sync(project, config) == 2


def test_sync_reads_the_project_config(
    tmp_path: Path, make_repo, write_config, monkeypatch
) -> None:
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    write_config(project / "skill-tools.yaml", source, tmp_path / "index.json")
    with (project / "skill-tools.yaml").open("a", encoding="utf-8") as handle:
        handle.write("install_skills: [beta]\n")
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("SKILL_TOOLS_CONFIG", raising=False)
    assert main(["sync-skills"], cwd=project) == 0
    assert _managed(project) == {BETA}
