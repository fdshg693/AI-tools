from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from skill_tools.cli import main
from skill_tools.config import DEFAULT_SELF_SKILL, load_config, user_config_path
from skill_tools.install.scope import InstallScope, resolve_scope
from skill_tools.models import ConfigError


@pytest.fixture(autouse=True)
def isolated_global_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.delenv("SKILL_TOOLS_CONFIG", raising=False)


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    elsewhere = tmp_path / "elsewhere"
    project.mkdir()
    elsewhere.mkdir()
    return project, elsewhere


def test_resolve_scope_defaults_to_cwd(tmp_path: Path) -> None:
    scope = resolve_scope(Namespace(), tmp_path)
    root = tmp_path.resolve()
    assert scope == InstallScope(
        kind="project", root=root, state_dir=root / ".skill-tools", config_dir=root
    )
    assert not scope.explicit


def test_resolve_scope_resolves_relative_project_dir_against_cwd(tmp_path: Path) -> None:
    (tmp_path / "work" / "target").mkdir(parents=True)
    scope = resolve_scope(Namespace(project_dir=Path("target")), tmp_path / "work")
    assert scope.root == (tmp_path / "work" / "target").resolve()
    assert scope.state_dir == scope.root / ".skill-tools"
    assert scope.config_dir == scope.root
    assert scope.explicit


def test_resolve_scope_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="--project-dir"):
        resolve_scope(Namespace(project_dir=tmp_path / "missing"), tmp_path)
    assert not (tmp_path / "missing").exists()


def test_load_config_reads_yaml_from_config_dir_not_cwd(tmp_path: Path) -> None:
    project, elsewhere = _dirs(tmp_path)
    (project / "skill-tools.yaml").write_text("self_skill: project/SKILL.md\n", encoding="utf-8")
    (elsewhere / "skill-tools.yaml").write_text("self_skill: cwd/SKILL.md\n", encoding="utf-8")

    assert load_config(cwd=elsewhere).self_skill == "cwd/SKILL.md"
    config = load_config(cwd=elsewhere, config_dir=project)
    assert config.self_skill == "project/SKILL.md"
    assert config.cwd_config_path == project.resolve() / "skill-tools.yaml"
    skipped = load_config(cwd=elsewhere, config_dir=None)
    assert skipped.self_skill == DEFAULT_SELF_SKILL
    assert skipped.cwd_config_path is None


def test_missing_project_dir_exits_2_without_creating_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing"
    assert main(["installed-skills", "--project-dir", str(missing)], cwd=tmp_path) == 2
    assert "--project-dir" in capsys.readouterr().err
    assert not missing.exists()


def test_list_skills_does_not_accept_project_dir(tmp_path: Path) -> None:
    assert main(["list-skills", "--project-dir", str(tmp_path)], cwd=tmp_path) == 2


def test_skill_lifecycle_targets_project_dir_from_another_cwd(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    project, elsewhere = _dirs(tmp_path)
    # A source inside the project is recorded with a project-relative path, so
    # update must resolve it against the project root, not the CWD.
    source = make_repo(project / "source")
    config = write_config(tmp_path / "config.yaml", source, tmp_path / "index.json")
    scoped = ["--project-dir", str(project)]

    assert main(["install-skills", "--config", str(config), *scoped, "alpha"], cwd=elsewhere) == 0
    assert (project / ".claude" / "skills" / "alpha" / "SKILL.md").is_file()
    assert not (elsewhere / ".claude").exists()
    assert not (elsewhere / ".skill-tools").exists()
    manifest = json.loads((project / ".skill-tools" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["entries"][0]["source"]["path"] == "source"
    assert str(project.resolve() / ".claude" / "skills" / "alpha") in capsys.readouterr().out

    assert main(["installed-skills", *scoped, "--json"], cwd=elsewhere) == 0
    entries = json.loads(capsys.readouterr().out)
    assert [entry["installPath"] for entry in entries] == [".claude/skills/alpha"]
    assert main(["installed-skills", "--json"], cwd=elsewhere) == 0
    assert json.loads(capsys.readouterr().out) == []

    assert main(["update-skills", "--config", str(config), *scoped, "alpha"], cwd=elsewhere) == 0
    assert "update\tplugins/one/skills/alpha/SKILL.md\t.claude/skills/alpha" in (
        capsys.readouterr().out
    )

    assert main(["remove-skills", *scoped, "alpha"], cwd=elsewhere) == 0
    assert not (project / ".claude" / "skills" / "alpha").exists()


def test_project_dir_uses_the_project_yaml_instead_of_the_cwd_yaml(
    tmp_path: Path, make_repo, write_config
) -> None:
    project, elsewhere = _dirs(tmp_path)
    source = make_repo(tmp_path / "source")
    write_config(project / "skill-tools.yaml", source, tmp_path / "index.json")
    with (project / "skill-tools.yaml").open("a", encoding="utf-8") as stream:
        stream.write("skills:\n  plugins/one/skills/alpha/SKILL.md:\n    destination: custom\n")
    (elsewhere / "skill-tools.yaml").write_text(
        "skills:\n  plugins/one/skills/alpha/SKILL.md:\n    destination: from-cwd\n",
        encoding="utf-8",
    )

    assert main(["install-skills", "--project-dir", str(project), "alpha"], cwd=elsewhere) == 0
    assert (project / "custom" / "alpha" / "SKILL.md").is_file()
    assert not (project / "from-cwd").exists()


def test_config_show_ignores_cwd_yaml_when_project_has_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    project, elsewhere = _dirs(tmp_path)
    source = make_repo(tmp_path / "source")
    write_config(elsewhere / "skill-tools.yaml", source, tmp_path / "index.json")

    assert main(["config", "show", "--project-dir", str(project)], cwd=elsewhere) == 0
    out = capsys.readouterr().out
    assert "source.type: github" in out
    assert str(source.resolve()) not in out
    assert f"config.cwd: {elsewhere.resolve() / 'skill-tools.yaml'} (not read: --project-dir)" in (
        out
    )
    assert f"config.project: {project.resolve() / 'skill-tools.yaml'} (missing)" in out

    assert main(["config", "show"], cwd=elsewhere) == 0
    out = capsys.readouterr().out
    assert f"source.path: {source.resolve()}" in out
    assert f"config.project: {elsewhere.resolve() / 'skill-tools.yaml'} (found)" in out


def test_config_show_reports_project_yaml_skipped_by_explicit_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    project, elsewhere = _dirs(tmp_path)
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "explicit.yaml", source, tmp_path / "index.json")
    (project / "skill-tools.yaml").write_text("self_skill: other/SKILL.md\n", encoding="utf-8")

    argv = ["config", "show", "--config", str(config), "--project-dir", str(project)]
    assert main(argv, cwd=elsewhere) == 0
    out = capsys.readouterr().out
    assert f"config: {config.resolve()}" in out
    assert "(not read: explicit config file)" in out
    assert "self_skill: other/SKILL.md" not in out


def test_hook_lifecycle_targets_project_dir_from_another_cwd(
    tmp_path: Path, make_repo, make_hook_repo, write_config
) -> None:
    project, elsewhere = _dirs(tmp_path)
    source = make_hook_repo(make_repo(tmp_path / "source"))
    config = write_config(tmp_path / "config.yaml", source, tmp_path / "index.json")
    scoped = ["--project-dir", str(project)]
    install = ["hooks", "install", "--config", str(config), *scoped, "--agent", "claude"]

    assert main([*install, "nested_rules"], cwd=elsewhere) == 0
    assert (project / ".claude" / "hooks" / "nested_rules.py").is_file()
    assert (project / ".claude" / "settings.json").is_file()
    assert not (elsewhere / ".claude").exists()
    manifest = json.loads((project / ".skill-tools" / "manifest.json").read_text(encoding="utf-8"))
    assert [entry["hookId"] for entry in manifest["hooks"]] == ["nested_rules"]

    assert main(["hooks", "update", "--config", str(config), *scoped], cwd=elsewhere) == 0
    assert main(["hooks", "remove", *scoped], cwd=elsewhere) == 0
    assert not (project / ".claude" / "hooks" / "nested_rules.py").exists()


def test_non_distributable_hook_installs_into_its_own_repo_via_project_dir(
    tmp_path: Path, make_repo, make_hook_repo, write_config
) -> None:
    _, elsewhere = _dirs(tmp_path)
    source = make_hook_repo(make_repo(tmp_path / "source"))
    config = write_config(tmp_path / "config.yaml", source, tmp_path / "index.json")
    argv = ["hooks", "install", "--config", str(config), "--agent", "claude", "--dry-run"]

    assert main([*argv, "--project-dir", str(source), "repo_only"], cwd=elsewhere) == 0
    assert main([*argv, "repo_only"], cwd=elsewhere) == 2


# --- --global -----------------------------------------------------------------


def test_resolve_global_scope(isolated_home: dict[str, Path], tmp_path: Path) -> None:
    scope = resolve_scope(Namespace(global_scope=True), tmp_path)
    assert scope == InstallScope(
        kind="global",
        root=isolated_home["home"],
        state_dir=isolated_home["state"],
        config_dir=None,
        explicit=True,
    )
    with pytest.raises(ConfigError, match="--global"):
        resolve_scope(Namespace(global_scope=True, project_dir=tmp_path), tmp_path)


def test_global_and_project_dir_are_mutually_exclusive(
    isolated_home: dict[str, Path], tmp_path: Path
) -> None:
    argv = ["installed-skills", "--global", "--project-dir", str(tmp_path)]
    assert main(argv, cwd=tmp_path) == 2


def test_global_skill_lifecycle_keeps_state_outside_home(
    isolated_home: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
) -> None:
    home, state = isolated_home["home"], isolated_home["state"]
    assert not state.is_relative_to(home)
    _, elsewhere = _dirs(tmp_path)
    # A source under home must still be recorded as an absolute path.
    source = make_repo(home / "src")
    global_config = user_config_path()
    global_config.parent.mkdir(parents=True)
    write_config(global_config, source, tmp_path / "index.json")
    # A CWD yaml must not change where --global installs.
    (elsewhere / "skill-tools.yaml").write_text(
        "global_destination: from-cwd\n"
        "skills:\n  plugins/one/skills/alpha/SKILL.md:\n    destination: from-cwd\n",
        encoding="utf-8",
    )

    assert main(["install-skills", "--global", "--dry-run", "alpha"], cwd=elsewhere) == 0
    assert capsys.readouterr().out.strip().endswith("\t~/.claude/skills/alpha")
    assert not (home / ".claude").exists()

    assert main(["install-skills", "--global", "alpha"], cwd=elsewhere) == 0
    capsys.readouterr()
    installed = home / ".claude" / "skills" / "alpha"
    assert (installed / "SKILL.md").is_file()
    assert not (home / ".skill-tools").exists()
    assert not (elsewhere / ".skill-tools").exists()
    assert not (state / "transaction.json").exists()
    manifest = json.loads((state / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["entries"][0]
    assert entry["installPath"] == ".claude/skills/alpha"
    assert entry["source"]["path"] == str(source.resolve())

    assert main(["installed-skills", "--global", "--json"], cwd=elsewhere) == 0
    assert [e["installPath"] for e in json.loads(capsys.readouterr().out)] == [
        ".claude/skills/alpha"
    ]
    assert main(["installed-skills", "--json"], cwd=elsewhere) == 0
    assert json.loads(capsys.readouterr().out) == []

    assert main(["update-skills", "--global", "alpha"], cwd=elsewhere) == 0
    assert "update\tplugins/one/skills/alpha/SKILL.md\t~/.claude/skills/alpha" in (
        capsys.readouterr().out
    )
    assert main(["remove-skills", "--global", "alpha"], cwd=elsewhere) == 0
    assert "remove\tplugins/one/skills/alpha/SKILL.md\t~/.claude/skills/alpha" in (
        capsys.readouterr().out
    )
    assert not installed.exists()
    manifest = json.loads((state / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["entries"] == []


def test_global_install_uses_target_global_destinations(
    isolated_home: dict[str, Path], tmp_path: Path, make_repo, write_config
) -> None:
    home = isolated_home["home"]
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "config.yaml", source, tmp_path / "index.json")
    with config.open("a", encoding="utf-8") as stream:
        stream.write(
            "targets:\n  claude:\n    destination: .claude/skills\n"
            "  antigravity:\n    destination: .agents/skills\n"
            "    global_destination: .gemini/config/skills\n"
        )
    argv = ["install-skills", "--config", str(config), "--global"]

    assert main([*argv, "--target", "claude,antigravity", "alpha"], cwd=tmp_path) == 0
    assert (home / ".claude" / "skills" / "alpha" / "SKILL.md").is_file()
    assert (home / ".gemini" / "config" / "skills" / "alpha" / "SKILL.md").is_file()
    assert not (home / ".agents").exists()


def test_global_install_rolls_back_with_state_outside_home(
    isolated_home: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_repo,
    write_config,
) -> None:
    from skill_tools.install import installer

    home, state = isolated_home["home"], isolated_home["state"]
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "config.yaml", source, tmp_path / "index.json")
    argv = ["install-skills", "--config", str(config), "--global"]
    assert main([*argv, "alpha"], cwd=tmp_path) == 0
    target = home / ".claude" / "skills" / "alpha"
    (target / "SKILL.md").write_text("local edit\n", encoding="utf-8")
    manifest_before = (state / "manifest.json").read_text(encoding="utf-8")

    def broken_make_entry(**_kwargs):
        raise OSError("simulated failure after the directory swap")

    monkeypatch.setattr(installer, "make_entry", broken_make_entry)
    assert main([*argv, "--overwrite", "alpha"], cwd=tmp_path) == 4

    assert (target / "SKILL.md").read_text(encoding="utf-8") == "local edit\n"
    assert (state / "manifest.json").read_text(encoding="utf-8") == manifest_before
    assert not (state / "transaction.json").exists()
    assert sorted(p.name for p in target.parent.iterdir()) == ["alpha"]


def test_global_recovers_an_interrupted_journal_in_the_state_dir(
    isolated_home: dict[str, Path], tmp_path: Path
) -> None:
    home, state = isolated_home["home"], isolated_home["state"]
    incoming = home / ".claude" / "skills" / ".alpha.skill-tools-incoming-x"
    incoming.mkdir(parents=True)
    (incoming / "SKILL.md").write_text("half\n", encoding="utf-8")
    state.mkdir(parents=True)
    (state / "transaction.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "phase": "applying",
                "manifestBefore": None,
                "operations": [
                    {
                        "target": ".claude/skills/alpha",
                        "incoming": ".claude/skills/.alpha.skill-tools-incoming-x",
                        "backup": ".claude/skills/.alpha.skill-tools-backup-x",
                        "hadTarget": False,
                        "replaced": False,
                        "newFiles": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert main(["installed-skills", "--global"], cwd=tmp_path) == 0
    assert not incoming.exists()
    assert not (state / "transaction.json").exists()


def test_install_and_update_refuse_a_project_rooted_at_home(
    isolated_home: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
) -> None:
    home = isolated_home["home"]
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "config.yaml", source, tmp_path / "index.json")

    for cwd in (home, tmp_path):  # home itself and one of its ancestors
        assert main(["install-skills", "--config", str(config), "alpha"], cwd=cwd) == 2
        assert "--global" in capsys.readouterr().err
        assert main(["update-skills", "--config", str(config)], cwd=cwd) == 2
        capsys.readouterr()
    argv = ["install-skills", "--config", str(config), "--project-dir", str(home), "alpha"]
    assert main(argv, cwd=tmp_path) == 2
    assert not (home / ".claude").exists()

    # Listing and removal stay available to migrate an existing home manifest.
    assert main(["installed-skills"], cwd=home) == 0
    assert main(["remove-skills"], cwd=home) == 0


def test_config_show_global(
    isolated_home: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project, elsewhere = _dirs(tmp_path)
    (elsewhere / "skill-tools.yaml").write_text("self_skill: cwd/SKILL.md\n", encoding="utf-8")

    assert main(["config", "show", "--global"], cwd=elsewhere) == 0
    out = capsys.readouterr().out
    assert "scope: global" in out
    assert f"scope.root: {isolated_home['home']}" in out
    assert f"scope.state_dir: {isolated_home['state']}" in out
    assert f"config.cwd: {elsewhere.resolve() / 'skill-tools.yaml'} (not read: --global)" in out
    assert "skills.global_destination: .claude/skills" in out
    assert "self_skill: cwd/SKILL.md" not in out
    assert "config.project" not in out
