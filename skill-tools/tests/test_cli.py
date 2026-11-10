from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from skill_tools.cli import main
from skill_tools.repo_tools import parse_repo_tools
from skill_tools.source import GitHubSource, LocalSource, display_skill_path


def test_cli_lists_and_installs_a_local_skill(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(
        tmp_path / "skill-tools.yaml", source, tmp_path / "cache" / "skill-index.json"
    )
    assert main(["list-skills", "--config", str(config)], cwd=tmp_path) == 0
    captured = capsys.readouterr()
    listed = display_skill_path(
        "plugins/one/skills/alpha/SKILL.md", {"type": "local", "path": str(source.resolve())}
    )
    assert f"{listed}\talpha\t2" in captured.out
    assert "source: local" in captured.err

    assert main(["install-skills", "--config", str(config), "alpha"], cwd=project) == 0
    assert (project / ".claude" / "skills" / "alpha" / "references" / "guide.md").is_file()
    manifest = json.loads((project / ".skill-tools" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["entries"][0]["canonicalId"] == "plugins/one/skills/alpha/SKILL.md"


def test_workflow_list_and_show_only_describe_configured_local_workflows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config, monkeypatch
) -> None:
    source = make_repo(tmp_path / "source")
    (source / "repo-workflows.yaml").write_text(
        "version: 1\n"
        "workflows:\n"
        "  - id: fixture-flow\n"
        "    title: Fixture flow\n"
        "    purpose: Find relevant fixture skills\n"
        "    requires_env: [EXTRA_KEY]\n"
        "    steps:\n"
        "      - id: search\n"
        "        skill: plugins/one/skills/alpha/SKILL.md\n"
        "        handoff: Read the matching result\n",
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "skill-tools.yaml", source, tmp_path / "index.json")
    monkeypatch.setattr("skill_tools.workflows.load_repo_tools", lambda source: ())

    assert main(["workflow", "list", "--config", str(config)], cwd=project) == 0
    listed = capsys.readouterr().out
    assert "fixture-flow" in listed
    assert "Find relevant fixture skills" in listed
    assert main(["workflow", "show", "fixture-flow", "--config", str(config)], cwd=project) == 0

    shown = capsys.readouterr().out
    assert "plugins/one/skills/alpha/SKILL.md" in shown
    assert "EXTRA_KEY" in shown
    assert "handoff: Read the matching result" in shown


def test_workflow_commands_reject_github_sources_before_network_access(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "skill-tools.yaml"
    config.write_text(
        "source:\n  type: github\n  owner: example\n  repository: skills\n  ref: main\n",
        encoding="utf-8",
    )

    assert main(["workflow", "list", "--config", str(config)], cwd=tmp_path) == 2

    assert "local source" in capsys.readouterr().err


def test_installed_reads_only_the_project_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config, monkeypatch
) -> None:
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "skill-tools.yaml", source, tmp_path / "index.json")
    assert main(["install-skills", "--config", str(config), "alpha"], cwd=project) == 0
    capsys.readouterr()
    monkeypatch.setattr(
        "skill_tools.cli.skills.create_source", lambda config: pytest.fail("source used")
    )

    assert main(["installed-skills", "--json"], cwd=project) == 0

    entries = json.loads(capsys.readouterr().out)
    assert entries[0]["canonicalId"] == "plugins/one/skills/alpha/SKILL.md"
    assert entries[0]["installPath"] == ".claude/skills/alpha"


def test_remove_refuses_drift_unless_forced_and_never_touches_unmanaged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    unmanaged = project / ".claude" / "skills" / "unmanaged"
    unmanaged.mkdir(parents=True)
    (unmanaged / "SKILL.md").write_text("keep\n", encoding="utf-8")
    assert main(["install-skills", "--config", str(config), "alpha"], cwd=project) == 0
    capsys.readouterr()
    (project / ".claude" / "skills" / "alpha" / "user.txt").write_text("keep?\n", encoding="utf-8")

    assert main(["remove-skills", "alpha"], cwd=project) == 4
    assert "extra files" in capsys.readouterr().err
    assert main(["remove-skills", "alpha", "--force"], cwd=project) == 0

    capsys.readouterr()
    assert not (project / ".claude" / "skills" / "alpha").exists()
    assert (unmanaged / "SKILL.md").read_text(encoding="utf-8") == "keep\n"


def test_update_replaces_a_clean_managed_bundle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    assert main(["install-skills", "--config", str(config), "alpha"], cwd=project) == 0
    capsys.readouterr()
    (source / "plugins" / "one" / "skills" / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: Updated\n---\n", encoding="utf-8"
    )

    assert main(["update-skills", "--config", str(config), "alpha"], cwd=project) == 0

    assert "Updated" in (project / ".claude" / "skills" / "alpha" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "update" in capsys.readouterr().out


def test_update_refuses_explicit_source_switch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    other_source = make_repo(tmp_path / "other-source")
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    other_config = write_config(tmp_path / "other.yaml", other_source, tmp_path / "index.json")
    assert main(["install-skills", "--config", str(config), "alpha"], cwd=project) == 0
    capsys.readouterr()
    before = (project / ".claude" / "skills" / "alpha" / "SKILL.md").read_bytes()

    assert main(["update-skills", "--config", str(other_config), "alpha"], cwd=project) == 4

    assert (project / ".claude" / "skills" / "alpha" / "SKILL.md").read_bytes() == before
    assert "source" in capsys.readouterr().err


def test_update_force_removes_extra_files_from_managed_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    assert main(["install-skills", "--config", str(config), "alpha"], cwd=project) == 0
    capsys.readouterr()
    extra = project / ".claude" / "skills" / "alpha" / "user.txt"
    extra.write_text("local content\n", encoding="utf-8")

    assert main(["update-skills", "--config", str(config), "--force", "alpha"], cwd=project) == 0

    assert not extra.exists()
    assert "force" in capsys.readouterr().out


def test_install_accepts_displayed_local_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    displayed = display_skill_path(
        "plugins/one/skills/alpha/SKILL.md", {"type": "local", "path": str(source.resolve())}
    )
    assert (
        main(["install-skills", "--config", str(config), "--dry-run", displayed], cwd=project) == 0
    )
    captured = capsys.readouterr()
    assert displayed in captured.out
    assert str((project / ".claude" / "skills" / "alpha").resolve()) in captured.out


def test_install_dry_run_does_not_copy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    assert main(["install-skills", "--config", str(config), "--dry-run", "alpha"], cwd=project) == 0
    assert "would install" in capsys.readouterr().out
    assert not (project / ".claude" / "skills" / "alpha").exists()


def test_install_dry_run_shows_each_selected_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "cfg.yaml"
    config.write_text(
        f"source:\n  type: local\n  path: {source.as_posix()}\n"
        "targets:\n  claude:\n    destination: .claude/skills\n"
        "  agents:\n    destination: .agents/skills\n",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "install-skills",
                "--config",
                str(config),
                "--target",
                "claude,agents",
                "--dry-run",
                "alpha",
            ],
            cwd=project,
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "claude\t.claude/skills/alpha" in output
    assert "agents\t.agents/skills/alpha" in output
    assert not (project / ".claude").exists()


@pytest.mark.parametrize("target_arg", ["missing", "claude,claude", ",claude", "claude,"])
def test_install_rejects_invalid_target_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, target_arg: str
) -> None:
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "cfg.yaml"
    config.write_text(
        f"source:\n  type: local\n  path: {source.as_posix()}\n"
        "targets:\n  claude:\n    destination: .claude/skills\n",
        encoding="utf-8",
    )

    assert (
        main(
            ["install-skills", "--config", str(config), "--target", target_arg, "alpha"],
            cwd=project,
        )
        == 2
    )
    assert "target" in capsys.readouterr().err.lower()


def test_commands_are_cwd_independent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config, embedder
) -> None:
    source = make_repo(tmp_path / "source")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    index_path = tmp_path / "cache" / "skill-index.json"
    config = write_config(tmp_path / "cfg.yaml", source, index_path)
    assert main(["list-skills", "--config", str(config)], cwd=elsewhere) == 0
    assert "alpha" in capsys.readouterr().out
    assert main(["build-index", "--config", str(config)], cwd=elsewhere, embedder=embedder) == 0
    captured = capsys.readouterr()
    assert str(index_path.resolve()) in captured.out
    assert (
        main(
            ["search", "--config", str(config), "--query", "alpha", "--json"],
            cwd=elsewhere,
            embedder=embedder,
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["path"] == display_skill_path(
        "plugins/one/skills/alpha/SKILL.md", {"type": "local", "path": str(source.resolve())}
    )
    assert payload[0]["status"] == {"key": "unset"}
    assert main(["config", "show", "--config", str(config)], cwd=elsewhere) == 0
    shown = capsys.readouterr().out
    assert "OPENROUTER" not in shown
    assert "source.type: local" in shown
    assert str(source.resolve()) in shown


def test_github_search_uses_index_without_resolving_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
    embedder,
) -> None:
    source = make_repo(tmp_path / "source")
    index_path = tmp_path / "index.json"
    config = tmp_path / "cfg.yaml"
    config.write_text(
        "source:\n  type: github\n  owner: owner\n  repository: repo\n  ref: main\n"
        f"index:\n  path: {index_path.as_posix()}\n",
        encoding="utf-8",
    )

    def fail_init(self, owner, repository, ref="main"):
        raise AssertionError("search must not resolve GitHub")

    local_config = write_config(tmp_path / "local.yaml", source, index_path)
    assert (
        main(["build-index", "--config", str(local_config)], cwd=tmp_path, embedder=embedder) == 0
    )
    capsys.readouterr()
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    raw["source"] = {
        "descriptor": {
            "type": "github",
            "owner": "owner",
            "repository": "repo",
            "ref": "main",
            "commit": "abc123",
        },
        "fingerprint": {
            "type": "github",
            "owner": "owner",
            "repository": "repo",
            "commit": "abc123",
        },
        "fingerprintKey": "key",
    }
    index_path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(GitHubSource, "__init__", fail_init)
    (tmp_path / "unrelated").mkdir()
    assert (
        main(
            ["search", "--config", str(config), "--query", "alpha", "--top", "1"],
            cwd=tmp_path / "unrelated",
            embedder=embedder,
        )
        == 0
    )
    table = capsys.readouterr().out
    assert table.splitlines()[0] == "score\tcanonical_id\tpath\tname\tsnippet"
    assert "https://github.com/owner/repo/blob/abc123/plugins/one/skills/alpha/SKILL.md" in table


def test_search_reports_missing_index_and_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
    embedder,
) -> None:
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "missing.json")
    monkeypatch.setattr("skill_tools.cli.index_cmd.resolve_api_key", lambda: None)
    assert main(["search", "--config", str(config), "--query", "alpha"]) == 1
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err
    assert main(["search", "--config", str(config), "--query", "alpha"], embedder=embedder) == 2
    assert "not found" in capsys.readouterr().err


def test_fingerprint_mismatch_is_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config, embedder
) -> None:
    source = make_repo(tmp_path / "source")
    other = make_repo(tmp_path / "other")
    index_path = tmp_path / "index.json"
    built = write_config(tmp_path / "built.yaml", source, index_path)
    used = write_config(tmp_path / "used.yaml", other, index_path)
    assert main(["build-index", "--config", str(built)], embedder=embedder) == 0
    capsys.readouterr()
    assert main(["search", "--config", str(used), "--query", "alpha"], embedder=embedder) == 2
    assert "another source" in capsys.readouterr().err


def test_config_show_does_not_print_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "super-secret-key")
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    assert main(["config", "show", "--config", str(config)], cwd=tmp_path) == 0
    captured = capsys.readouterr()
    assert "super-secret-key" not in captured.out
    assert "super-secret-key" not in captured.err
    assert "index: missing" in captured.out
    assert "source.fingerprint" not in captured.out


def test_config_show_does_not_compute_fingerprint_and_prints_package_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
) -> None:
    def fail_fingerprint(self):
        raise AssertionError("config show must not hash the source tree")

    monkeypatch.setattr(LocalSource, "fingerprint", property(fail_fingerprint))
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")

    assert main(["config", "show", "--config", str(config)], cwd=tmp_path) == 0

    out = capsys.readouterr().out
    assert f"source.path: {source.resolve()}" in out
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    readme = pyproject.parent / "README.md"
    assert f"package.pyproject: {pyproject}" in out
    assert f"package.readme: {readme}" in out


def test_config_show_prints_stored_fingerprint_for_a_matching_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
    embedder,
) -> None:
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0
    capsys.readouterr()

    def fail_fingerprint(self):
        raise AssertionError("config show must not hash the source tree")

    monkeypatch.setattr(LocalSource, "fingerprint", property(fail_fingerprint))
    assert main(["config", "show", "--config", str(config)], cwd=tmp_path) == 0
    assert "source.fingerprint:" in capsys.readouterr().out


def test_config_show_without_a_shipped_pyproject_still_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
) -> None:
    monkeypatch.setattr("skill_tools.cli.config_cmd.pyproject_path", lambda: None)
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")

    assert main(["config", "show", "--config", str(config)], cwd=tmp_path) == 0

    out = capsys.readouterr().out
    assert "package.pyproject: (not shipped with this install)" in out
    assert "package.dir:" in out
    assert "package.readme" not in out


def test_config_init_creates_global_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    assert main(["config", "init"], cwd=tmp_path) == 0

    captured = capsys.readouterr()
    assert "Created global config:" in captured.out
    written = (tmp_path / "appdata" / "skill-tools" / "skill-tools.yaml").read_text(
        encoding="utf-8"
    )
    assert "owner: fdshg693" in written
    assert f"self_skill: {SELF_SKILL_DEFAULT}" in written


SELF_SKILL_DEFAULT = "claude-plugins/my-tools/skills/skill-tools-cli/SKILL.md"


def test_embedded_default_self_skill_is_the_companion_skill() -> None:
    from skill_tools.config import _embedded_default_data

    assert _embedded_default_data()["self_skill"] == SELF_SKILL_DEFAULT


def test_version_alone_is_unchanged_by_fb_mode(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("skill-tools ")


def test_fb_combined_with_a_subcommand_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--fb", "x", "list-skills"], cwd=tmp_path) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err


def test_help_mentions_fb(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    assert "--fb" in capsys.readouterr().out


def test_config_show_prints_fb_path_and_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("SKILL_TOOLS_FB_DIR", str(tmp_path / "from-env"))

    assert main(["config", "show"], cwd=tmp_path) == 0

    out = capsys.readouterr().out
    assert "fb.path:" in out
    assert "SKILL_TOOLS_FB_DIR" in out
    assert str((tmp_path / "from-env").resolve()) in out


def test_old_skill_command_names_are_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for old in ("list", "install", "installed", "update", "remove"):
        assert main([old], cwd=tmp_path) == 2
        assert "invalid choice" in capsys.readouterr().err


def test_install_skills_self_expands_to_the_configured_skill(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "skill-tools.yaml", source, tmp_path / "index.json")
    with config.open("a", encoding="utf-8") as handle:
        handle.write("self_skill: plugins/one/skills/alpha/SKILL.md\n")

    assert main(["install-skills", "--config", str(config), "--dry-run", "self"], cwd=project) == 0
    assert "would install" in capsys.readouterr().out
    assert not (project / ".claude" / "skills" / "alpha").exists()

    assert main(["install-skills", "--config", str(config), "self"], cwd=project) == 0
    assert (project / ".claude" / "skills" / "alpha" / "SKILL.md").is_file()
    manifest = json.loads((project / ".skill-tools" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["entries"][0]["canonicalId"] == "plugins/one/skills/alpha/SKILL.md"


def test_install_skills_self_is_reserved_over_a_skill_named_self(
    tmp_path: Path, make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    shadow = source / "plugins" / "one" / "skills" / "self"
    shadow.mkdir()
    (shadow / "SKILL.md").write_bytes(
        b"---\nname: self\ndescription: Shadow skill\n---\n\n# self\n"
    )
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "skill-tools.yaml", source, tmp_path / "index.json")
    with config.open("a", encoding="utf-8") as handle:
        handle.write("self_skill: plugins/one/skills/alpha/SKILL.md\n")

    assert main(["install-skills", "--config", str(config), "self"], cwd=project) == 0
    assert (project / ".claude" / "skills" / "alpha").is_dir()
    assert not (project / ".claude" / "skills" / "self").exists()


def test_install_skills_self_with_another_selector_installs_both(
    tmp_path: Path, make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "skill-tools.yaml", source, tmp_path / "index.json")
    with config.open("a", encoding="utf-8") as handle:
        handle.write("self_skill: plugins/one/skills/alpha/SKILL.md\n")

    assert main(["install-skills", "--config", str(config), "self", "beta"], cwd=project) == 0
    assert (project / ".claude" / "skills" / "alpha").is_dir()
    assert (project / ".claude" / "skills" / "beta").is_dir()


def test_install_skills_self_reports_a_missing_catalog_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "skill-tools.yaml", source, tmp_path / "index.json")

    assert main(["install-skills", "--config", str(config), "self"], cwd=project) == 2
    assert "skill not found" in capsys.readouterr().err


def test_install_skills_requires_a_selector(tmp_path: Path) -> None:
    assert main(["install-skills"], cwd=tmp_path) == 2


@pytest.mark.parametrize("value", ["", "../escape/SKILL.md", "/abs/SKILL.md", 3])
def test_self_skill_must_be_a_safe_repository_relative_path(
    tmp_path: Path, make_repo, write_config, value, capsys: pytest.CaptureFixture[str]
) -> None:
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "skill-tools.yaml", source, tmp_path / "index.json")
    with config.open("a", encoding="utf-8") as handle:
        handle.write(f"self_skill: {json.dumps(value)}\n")

    assert main(["config", "show", "--config", str(config)], cwd=tmp_path) == 2
    assert "self_skill" in capsys.readouterr().err


def test_config_show_prints_the_resolved_self_skill(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "skill-tools.yaml", source, tmp_path / "index.json")
    assert main(["config", "show", "--config", str(config)], cwd=tmp_path) == 0
    assert f"self_skill: {SELF_SKILL_DEFAULT}" in capsys.readouterr().out


def counting_embedder(unit_vector, calls: list[list[str]]):
    def _embedder(texts):
        batch = list(texts)
        calls.append(batch)
        return [unit_vector(1.0) for _ in batch]

    return _embedder


def test_build_index_skips_a_fresh_index_unless_forced(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
    unit_vector,
) -> None:
    source = make_repo(tmp_path / "source")
    index_path = tmp_path / "index.json"
    config = write_config(tmp_path / "cfg.yaml", source, index_path)
    calls: list[list[str]] = []
    embedder = counting_embedder(unit_vector, calls)

    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0
    first = capsys.readouterr().out
    assert "embedded: 2, reused: 0" in first
    assert len(calls) == 1

    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0
    skipped = capsys.readouterr().out
    assert "Index is up to date" in skipped
    assert "--force" in skipped
    assert len(calls) == 1

    assert (
        main(["build-index", "--config", str(config), "--force"], cwd=tmp_path, embedder=embedder)
        == 0
    )
    forced = capsys.readouterr().out
    assert "embedded: 0, reused: 2" in forced
    assert len(calls) == 1


def test_build_index_max_age_days_zero_always_rebuilds(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
    embedder,
) -> None:
    source = make_repo(tmp_path / "source")
    index_path = tmp_path / "index.json"
    config = write_config(tmp_path / "cfg.yaml", source, index_path)
    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0
    first_built_at = json.loads(index_path.read_text(encoding="utf-8"))["builtAt"]
    capsys.readouterr()

    assert (
        main(
            ["build-index", "--config", str(config), "--max-age-days", "0"],
            cwd=tmp_path,
            embedder=embedder,
        )
        == 0
    )
    assert "Wrote" in capsys.readouterr().out
    assert json.loads(index_path.read_text(encoding="utf-8"))["builtAt"] >= first_built_at


def test_build_index_rebuilds_a_stale_index(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
    embedder,
) -> None:
    source = make_repo(tmp_path / "source")
    index_path = tmp_path / "index.json"
    config = write_config(tmp_path / "cfg.yaml", source, index_path)
    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0
    capsys.readouterr()

    raw = json.loads(index_path.read_text(encoding="utf-8"))
    raw["builtAt"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    index_path.write_text(json.dumps(raw), encoding="utf-8")

    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0
    assert "embedded: 0, reused: 2" in capsys.readouterr().out


def test_search_tolerates_an_unrelated_fingerprint_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config, embedder
) -> None:
    source = make_repo(tmp_path / "source")
    index_path = tmp_path / "index.json"
    config = write_config(tmp_path / "cfg.yaml", source, index_path)
    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0
    capsys.readouterr()

    (source / "unrelated.md").write_text("an unrelated change\n", encoding="utf-8")
    assert main(["search", "--config", str(config), "--query", "alpha"], embedder=embedder) == 0
    captured = capsys.readouterr()
    assert "alpha" in captured.out
    assert "another source" not in captured.err


def test_search_warns_about_a_stale_index(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config, embedder
) -> None:
    source = make_repo(tmp_path / "source")
    index_path = tmp_path / "index.json"
    config = write_config(tmp_path / "cfg.yaml", source, index_path)
    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0
    capsys.readouterr()

    raw = json.loads(index_path.read_text(encoding="utf-8"))
    raw["builtAt"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    index_path.write_text(json.dumps(raw), encoding="utf-8")
    assert main(["search", "--config", str(config), "--query", "alpha"], embedder=embedder) == 0
    assert "30 days old" in capsys.readouterr().err

    del raw["builtAt"]
    index_path.write_text(json.dumps(raw), encoding="utf-8")
    assert main(["search", "--config", str(config), "--query", "alpha"], embedder=embedder) == 0
    assert "no known build time" in capsys.readouterr().err


def test_body_change_rebuilds_fresh_lexical_index_without_reembedding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config, unit_vector
) -> None:
    source = make_repo(tmp_path / "source")
    index_path = tmp_path / "index.json"
    config = write_config(tmp_path / "cfg.yaml", source, index_path)
    calls: list[list[str]] = []
    embedder = counting_embedder(unit_vector, calls)
    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0
    capsys.readouterr()
    calls.clear()

    skill = source / "plugins" / "one" / "skills" / "alpha" / "SKILL.md"
    skill.write_text(
        "---\nname: alpha\ndescription: Description for alpha\n---\n\n"
        "Use the prismatic-lockfile recovery protocol.\n",
        encoding="utf-8",
    )

    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0
    built = capsys.readouterr()
    assert "Wrote" in built.out
    assert "embedded: 0, reused: 2" in built.out
    assert calls == []
    assert (
        main(
            ["search", "--config", str(config), "--query", "prismatic-lockfile", "--json"],
            cwd=tmp_path,
            embedder=embedder,
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)[0]
    assert result["canonicalId"] == "plugins/one/skills/alpha/SKILL.md"
    assert "prismatic-lockfile" in result["snippet"]


def test_metadata_change_rebuilds_fresh_index_and_reembeds_only_changed_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config, unit_vector
) -> None:
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    calls: list[list[str]] = []
    embedder = counting_embedder(unit_vector, calls)
    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0
    capsys.readouterr()
    calls.clear()

    skill = source / "plugins" / "one" / "skills" / "alpha" / "SKILL.md"
    skill.write_text(
        "---\nname: alpha\ndescription: Updated metadata\n---\n\n# unchanged body\n",
        encoding="utf-8",
    )

    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0

    assert "embedded: 1, reused: 1" in capsys.readouterr().out
    assert len(calls) == 1
    assert calls[0] == ["name: alpha\ndescription: Updated metadata"]


def test_search_text_and_json_include_identity_and_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config, embedder
) -> None:
    source = make_repo(tmp_path / "source")
    skill = source / "plugins" / "one" / "skills" / "alpha" / "SKILL.md"
    skill.write_text(
        "---\nname: alpha\ndescription: Description for alpha\n---\n\n"
        "Run the iridescent-bundle verifier.\n",
        encoding="utf-8",
    )
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0
    capsys.readouterr()

    assert (
        main(
            ["search", "--config", str(config), "--query", "iridescent-bundle", "--json"],
            embedder=embedder,
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)[0]
    assert payload["canonicalId"] == "plugins/one/skills/alpha/SKILL.md"
    assert "iridescent-bundle" in payload["snippet"]

    assert (
        main(
            ["search", "--config", str(config), "--query", "iridescent-bundle"],
            embedder=embedder,
        )
        == 0
    )
    table = capsys.readouterr().out
    assert table.splitlines()[0] == "score\tcanonical_id\tpath\tname\tsnippet"
    assert "plugins/one/skills/alpha/SKILL.md" in table
    assert "iridescent-bundle" in table


def test_list_tools_includes_every_entry_regardless_of_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")

    assert main(["list-tools", "--config", str(config)], cwd=tmp_path) == 0

    captured = capsys.readouterr()
    lines = {line.split("\t")[0]: line.split("\t") for line in captured.out.splitlines()}
    assert set(lines) == {"alpha-tool", "beta-tool", "gamma-tool"}
    assert lines["gamma-tool"][1] == str((source / "tools" / "gamma-tool").resolve())
    assert lines["gamma-tool"][2] == "uv tool install --editable tools/gamma-tool"
    assert lines["alpha-tool"][3] == "Alpha tool summary"
    assert lines["gamma-tool"][3] == "Gamma tool summary"
    assert lines["beta-tool"][3] == ""
    assert "source: local" in captured.err


def test_list_tools_json_payload(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")

    assert main(["list-tools", "--config", str(config), "--json"], cwd=tmp_path) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    by_name = {entry["name"]: entry for entry in payload}
    assert set(by_name) == {"alpha-tool", "beta-tool", "gamma-tool"}
    assert by_name["alpha-tool"] == {
        "name": "alpha-tool",
        "path": display_skill_path(
            "tools/alpha-tool", {"type": "local", "path": str(source.resolve())}
        ),
        "install": "uv tool install --editable tools/alpha-tool",
        "description": "Alpha tool summary",
    }
    assert by_name["beta-tool"]["description"] == ""
    assert "source: local" in captured.err


def test_list_tools_fails_on_a_broken_description_locator(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    (source / "repo-tools.yaml").write_text(
        "tools:\n"
        "  alpha-tool:\n"
        "    path: tools/alpha-tool\n"
        "    install: run alpha\n"
        "    description: tools/alpha-tool/pyproject.toml#project.missing\n",
        encoding="utf-8",
    )
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")

    assert main(["list-tools", "--config", str(config)], cwd=tmp_path) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "alpha-tool" in captured.err
    assert "project.missing" in captured.err


def test_install_tools_dry_run_prints_all_without_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
) -> None:
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")

    def fail_install(*args, **kwargs):
        raise AssertionError("dry-run must not execute install commands")

    monkeypatch.setattr("skill_tools.cli.tools_cmd.install_repo_tools", fail_install)

    assert main(["install-tools", "--config", str(config), "--dry-run"], cwd=tmp_path) == 0
    out = capsys.readouterr().out
    assert out.count("would install\t") == 3
    assert "gamma-tool" in out


def test_install_tools_runs_selected_commands_in_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
) -> None:
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    calls: list[tuple[tuple[str, ...], Path]] = []

    def recorder(selected, root):
        calls.append((tuple(tool.key for tool in selected), root))
        return selected

    monkeypatch.setattr("skill_tools.cli.tools_cmd.install_repo_tools", recorder)

    assert main(["install-tools", "--config", str(config), "beta-tool"], cwd=tmp_path) == 0
    assert calls == [(("beta-tool",), source.resolve())]
    assert "install\tbeta-tool" in capsys.readouterr().out


def test_install_tools_rejects_a_github_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make_repo,
    write_config,
) -> None:
    from skill_tools.cli import tools_cmd

    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    remote = SimpleNamespace(
        descriptor={
            "type": "github",
            "owner": "owner",
            "repository": "repo",
            "ref": "main",
            "commit": "sha",
        }
    )
    catalog = parse_repo_tools(
        yaml.safe_load("tools:\n  aim:\n    path: tools/aim\n    install: run aim\n")
    )
    monkeypatch.setattr(tools_cmd, "create_source", lambda loaded: remote)
    monkeypatch.setattr(tools_cmd, "load_repo_tools", lambda loaded: catalog)

    def fail_install(*args, **kwargs):
        raise AssertionError("a GitHub source must not execute install commands")

    monkeypatch.setattr(tools_cmd, "install_repo_tools", fail_install)

    assert main(["install-tools", "--config", str(config), "aim"], cwd=tmp_path) == 4
    assert "local source" in capsys.readouterr().err


def test_hooks_list_hides_repository_only_hooks_unless_all(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, make_hook_repo, write_config
) -> None:
    source = make_hook_repo(make_repo(tmp_path / "source"))
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")

    assert main(["hooks", "list", "--config", str(config)], cwd=tmp_path) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["nested_rules\tclaude,kilo\tInject nested rules"]
    assert "source: local" in captured.err

    assert main(["hooks", "list", "--config", str(config), "--all"], cwd=tmp_path) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == "repo_only\tclaude\tNeeds this repository (not distributable)"


def test_hooks_list_json_filters_by_agent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, make_hook_repo, write_config
) -> None:
    source = make_hook_repo(make_repo(tmp_path / "source"))
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")

    argv = ["hooks", "list", "--config", str(config), "--agent", "kilo", "--json"]
    assert main(argv, cwd=tmp_path) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [hook["id"] for hook in payload] == ["nested_rules"]
    assert list(payload[0]["agents"]) == ["kilo"]
    assert payload[0]["agents"]["kilo"]["main"] == "nested_rules.ts"
    assert payload[0]["agents"]["kilo"]["files"][1] == {
        "path": "hooks/generated/kilo/nested_rules.ts",
        "installPath": "nested_rules.ts",
    }

    assert main(["hooks", "list", "--config", str(config), "--agent", "codex"], cwd=tmp_path) == 0
    assert capsys.readouterr().out == "(no hooks)\n"


def test_hooks_list_rejects_an_unknown_agent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, make_hook_repo, write_config
) -> None:
    source = make_hook_repo(make_repo(tmp_path / "source"))
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")

    assert main(["hooks", "list", "--config", str(config), "--agent", "cline"], cwd=tmp_path) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_hooks_list_without_repo_hooks_yaml_is_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, write_config
) -> None:
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")

    assert main(["hooks", "list", "--config", str(config)], cwd=tmp_path) == 0
    assert capsys.readouterr().out == "(no hooks)\n"


def test_broken_hook_catalog_fails_hooks_list_but_not_skill_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], make_repo, make_hook_repo, write_config
) -> None:
    source = make_hook_repo(make_repo(tmp_path / "source"))
    (source / "hooks" / "generated" / "catalog.json").write_text("{", encoding="utf-8")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")

    assert main(["hooks", "list", "--config", str(config)], cwd=tmp_path) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "catalog.json" in captured.err

    assert main(["list-skills", "--config", str(config)], cwd=tmp_path) == 0
    assert "\talpha\t" in capsys.readouterr().out
