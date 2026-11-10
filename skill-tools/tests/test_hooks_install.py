from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from skill_tools.install import installer
from skill_tools.cli import main
from skill_tools.models import InstallError

AGENT_SPECS = {
    "codex": {"event": "PreToolUse", "matcher": "^Bash$", "statusMessage": "Checking"},
    "cursor": {"event": "postToolUse", "matcher": "Read"},
    "antigravity": {"event": "PreInvocation"},
}


def _catalog(hook_catalog: dict) -> dict:
    """The shared fixture catalog, with nested_rules also offered to codex/cursor/antigravity."""

    catalog = copy.deepcopy(hook_catalog)
    agents = catalog["hooks"][0]["agents"]
    for agent, registration in AGENT_SPECS.items():
        agents[agent] = {
            "runner": "python",
            "main": "nested_rules.py",
            "files": [{"path": f"{agent}/nested_rules.py", "installPath": "nested_rules.py"}],
            "seedFiles": [],
            "dependencies": [],
            "registrations": [registration],
        }
    return catalog


@pytest.fixture
def env(tmp_path: Path, make_repo, make_hook_repo, hook_catalog, write_config):
    source = make_hook_repo(make_repo(tmp_path / "source"), _catalog(hook_catalog))
    project = tmp_path / "project"
    project.mkdir()
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    return source, project, config


def _run(project: Path, config: Path, *argv: str) -> int:
    return main(["hooks", *argv[:1], "--config", str(config), *argv[1:]], cwd=project)


def _manifest(project: Path) -> dict:
    return json.loads((project / ".skill-tools" / "manifest.json").read_text(encoding="utf-8"))


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


ALL_AGENTS = "claude,codex,cursor,antigravity,kilo"


def test_install_places_registers_and_remove_restores_user_files(env, capsys) -> None:
    _, project, config = env
    settings = project / ".claude" / "settings.json"
    settings.parent.mkdir()
    user_settings = {
        "permissions": {"allow": ["Bash(ls)"]},
        "hooks": {
            "PreToolUse": [{"matcher": "Read", "hooks": [{"type": "command", "command": "me"}]}]
        },
    }
    settings.write_text(json.dumps(user_settings), encoding="utf-8")

    assert _run(project, config, "install", "--agent", ALL_AGENTS, "nested_rules") == 0
    out = capsys.readouterr().out
    assert "install\tnested_rules\tkilo\t.kilo/plugin/nested_rules.ts" in out
    assert "register\tnested_rules\tcursor\t.cursor/hooks.json postToolUse [Read]" in out

    for path in (
        ".claude/hooks/nested_rules.py",
        ".codex/hooks/nested_rules.py",
        ".cursor/hooks/nested_rules.py",
        ".agents/hooks/nested_rules.py",
        ".kilo/plugin/nested_rules.py",
        ".kilo/plugin/nested_rules.ts",
    ):
        assert (project / path).is_file(), path
    claude = _json(settings)
    assert claude["permissions"] == user_settings["permissions"]
    assert claude["hooks"]["PreToolUse"][0]["hooks"][0] == {"type": "command", "command": "me"}
    assert claude["hooks"]["PreToolUse"][0]["hooks"][1]["args"] == [
        "${CLAUDE_PROJECT_DIR}/.claude/hooks/nested_rules.py"
    ]
    assert claude["hooks"]["CwdChanged"] == [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "python",
                    "args": ["${CLAUDE_PROJECT_DIR}/.claude/hooks/nested_rules.py"],
                }
            ]
        }
    ]
    assert _json(project / ".codex" / "hooks.json")["hooks"]["PreToolUse"][0]["matcher"] == "^Bash$"
    assert _json(project / ".cursor" / "hooks.json")["version"] == 1
    assert "nested-rules" in _json(project / ".agents" / "hooks.json")

    manifest = _manifest(project)
    assert manifest["schemaVersion"] == 2
    assert {(e["hookId"], e["agent"]) for e in manifest["hooks"]} == {
        ("nested_rules", agent) for agent in ALL_AGENTS.split(",")
    }

    assert main(["hooks", "installed"], cwd=project) == 0
    assert "nested_rules\tkilo\t.kilo/plugin\t(placement only)" in capsys.readouterr().out

    assert main(["hooks", "remove"], cwd=project) == 0
    assert _json(settings) == user_settings
    for path in (".codex/hooks.json", ".cursor/hooks.json", ".agents/hooks.json"):
        assert not (project / path).exists(), path
    assert not (project / ".claude/hooks/nested_rules.py").exists()
    assert _manifest(project)["hooks"] == []


def test_dry_run_changes_nothing(env, capsys) -> None:
    _, project, config = env

    assert _run(project, config, "install", "--agent", "claude", "--dry-run", "nested_rules") == 0

    assert "would install\tnested_rules\tclaude" in capsys.readouterr().out
    assert list(project.iterdir()) == []


def test_agent_is_required_unless_configured(env, capsys) -> None:
    _, project, config = env

    assert _run(project, config, "install", "nested_rules") == 2
    assert "--agent is required" in capsys.readouterr().err

    config.write_text(
        config.read_text(encoding="utf-8") + "hooks:\n  default_agents: [kilo]\n",
        encoding="utf-8",
    )
    assert _run(project, config, "install", "nested_rules") == 0
    assert (project / ".kilo/plugin/nested_rules.ts").is_file()


def test_unsupported_agent_is_skipped_or_rejected(env, capsys) -> None:
    source, project, config = env

    assert _run(project, config, "install", "--agent", "codex", "nested_rules") == 0
    assert _run(project, config, "install", "--agent", "claude,codex", "repo_only") == 2
    capsys.readouterr()
    catalog = _json(source / "hooks/generated/catalog.json")
    del catalog["hooks"][0]["agents"]["cursor"]
    (source / "hooks/generated/catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    assert _run(project, config, "install", "--agent", "cursor", "nested_rules") == 2
    assert "does not support cursor" in capsys.readouterr().err


def test_existing_unmanaged_file_needs_overwrite_and_reinstall_needs_update(env, capsys) -> None:
    _, project, config = env
    existing = project / ".claude" / "hooks" / "nested_rules.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("mine\n", encoding="utf-8")

    assert _run(project, config, "install", "--agent", "claude", "nested_rules") == 4
    assert "--overwrite" in capsys.readouterr().err
    assert existing.read_text(encoding="utf-8") == "mine\n"

    assert _run(project, config, "install", "--agent", "claude", "--overwrite", "nested_rules") == 0
    assert existing.read_text(encoding="utf-8") == "# fixture\n"
    assert _run(project, config, "install", "--agent", "claude", "nested_rules") == 4
    assert "hooks update" in capsys.readouterr().err


def test_duplicate_unmanaged_registration_warns(env, capsys) -> None:
    _, project, config = env
    settings = project / ".claude" / "settings.json"
    settings.parent.mkdir()
    old = {"type": "command", "command": "python .claude/hooks/nested_rules.py"}
    settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [old]}]}}), encoding="utf-8")

    assert _run(project, config, "install", "--agent", "claude", "nested_rules") == 0

    assert "may run twice" in capsys.readouterr().err
    assert _json(settings)["hooks"]["Stop"] == [{"hooks": [old]}]


def test_jsonc_registration_file_is_left_untouched(env, capsys) -> None:
    _, project, config = env
    settings = project / ".codex" / "hooks.json"
    settings.parent.mkdir()
    settings.write_text('{\n  // mine\n  "hooks": {}\n}\n', encoding="utf-8")

    assert _run(project, config, "install", "--agent", "codex", "nested_rules") == 4

    assert "JSONC" in capsys.readouterr().err
    assert not (project / ".codex" / "hooks").exists()
    assert not (project / ".skill-tools" / "manifest.json").exists()


def test_private_hook_only_installs_into_its_own_repository(
    env, write_config, monkeypatch, capsys
) -> None:
    source, project, config = env
    monkeypatch.setattr("skill_tools.hooks.install.shutil.which", lambda _name: None)

    assert _run(project, config, "install", "--agent", "claude", "repo_only") == 2
    assert "not distributable" in capsys.readouterr().err

    self_config = write_config(source / "self.yaml", source, source / "index.json")
    assert (
        main(
            ["hooks", "install", "--config", str(self_config), "--agent", "claude", "repo_only"],
            cwd=source,
        )
        == 0
    )
    captured = capsys.readouterr()
    assert "skill-tools install-tools aim" in captured.err
    entry = _json(source / ".claude" / "settings.json")["hooks"]["Stop"][0]["hooks"][0]
    assert entry == {
        "type": "command",
        "command": "uv",
        "args": ["run", "--script", "${CLAUDE_PROJECT_DIR}/.claude/hooks/repo_only.py"],
        "timeout": 10,
    }


def test_seed_files_are_placed_once_and_kept_on_remove(env, write_config, capsys) -> None:
    source, _, _ = env
    self_config = write_config(source / "self.yaml", source, source / "index.json")
    seed = source / ".claude" / "hooks" / "config" / "repo_only.yaml"
    argv = ["--config", str(self_config)]

    assert main(["hooks", "install", *argv, "--agent", "claude", "repo_only"], cwd=source) == 0
    assert seed.read_text(encoding="utf-8") == "# fixture\n"
    seed.write_text("custom: true\n", encoding="utf-8")

    assert main(["hooks", "update", *argv], cwd=source) == 0
    assert "unchanged\trepo_only\tclaude" in capsys.readouterr().out
    assert main(["hooks", "remove", "repo_only"], cwd=source) == 0
    assert seed.read_text(encoding="utf-8") == "custom: true\n"
    assert not (source / ".claude" / "hooks" / "repo_only.py").exists()


def test_update_applies_catalog_changes_and_refuses_drift(env, capsys) -> None:
    source, project, config = env
    assert _run(project, config, "install", "--agent", "claude,codex", "nested_rules") == 0
    capsys.readouterr()

    catalog = _json(source / "hooks/generated/catalog.json")
    catalog["hooks"][0]["agents"]["claude"]["registrations"] = [
        {"event": "PreToolUse", "matcher": "Read|Edit", "timeout": 3}
    ]
    (source / "hooks/generated/catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    (source / "hooks/generated/claude/nested_rules.py").write_text("# v2\n", encoding="utf-8")

    assert _run(project, config, "update", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "would update\tnested_rules\tclaude\t.claude/hooks" in out
    assert "unchanged\tnested_rules\tcodex\t.codex/hooks" in out

    installed = project / ".claude" / "hooks" / "nested_rules.py"
    installed.write_text("# edited\n", encoding="utf-8")
    assert _run(project, config, "update", "nested_rules") == 4
    assert "modified" in capsys.readouterr().err
    assert _run(project, config, "update", "--force", "nested_rules") == 0

    assert installed.read_text(encoding="utf-8") == "# v2\n"
    hooks = _json(project / ".claude" / "settings.json")["hooks"]
    assert list(hooks) == ["PreToolUse"]
    assert hooks["PreToolUse"] == [
        {
            "matcher": "Read|Edit",
            "hooks": [
                {
                    "type": "command",
                    "command": "python",
                    "args": ["${CLAUDE_PROJECT_DIR}/.claude/hooks/nested_rules.py"],
                    "timeout": 3,
                }
            ],
        }
    ]


def test_update_refuses_explicit_source_switch(env, make_repo, make_hook_repo, tmp_path, capsys):
    _, project, config = env
    assert _run(project, config, "install", "--agent", "claude", "nested_rules") == 0
    other = make_hook_repo(make_repo(tmp_path / "other"))

    argv = ["hooks", "update", "--source", "local", "--repo", str(other), "nested_rules"]
    assert main(argv, cwd=project) == 4
    assert "refusing an implicit source switch" in capsys.readouterr().err


def test_hand_edited_registration_blocks_remove_unless_forced(env, capsys) -> None:
    _, project, config = env
    assert _run(project, config, "install", "--agent", "claude", "nested_rules") == 0
    settings = project / ".claude" / "settings.json"
    data = _json(settings)
    data["hooks"]["CwdChanged"][0]["hooks"][0]["timeout"] = 1
    settings.write_text(json.dumps(data), encoding="utf-8")

    assert main(["hooks", "remove", "nested_rules"], cwd=project) == 4
    assert "use --force" in capsys.readouterr().err
    assert (project / ".claude/hooks/nested_rules.py").is_file()

    assert main(["hooks", "remove", "--force", "nested_rules"], cwd=project) == 0
    assert "skipped" in capsys.readouterr().err
    remaining = _json(settings)["hooks"]
    assert list(remaining) == ["CwdChanged"]
    assert remaining["CwdChanged"][0]["hooks"][0]["timeout"] == 1


def test_skill_operations_keep_hook_records(env, capsys) -> None:
    _, project, config = env
    manifest_file = project / ".skill-tools" / "manifest.json"
    manifest_file.parent.mkdir()
    manifest_file.write_text('{"schemaVersion": 1, "entries": []}', encoding="utf-8")

    assert _run(project, config, "install", "--agent", "claude", "nested_rules") == 0
    assert main(["install-skills", "--config", str(config), "alpha"], cwd=project) == 0
    assert main(["remove-skills", "alpha"], cwd=project) == 0

    manifest = _manifest(project)
    assert manifest["schemaVersion"] == 2
    assert manifest["entries"] == []
    assert [entry["hookId"] for entry in manifest["hooks"]] == ["nested_rules"]


def test_failed_commit_restores_every_file(env, monkeypatch, capsys) -> None:
    _, project, config = env
    settings = project / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"env": {}}', encoding="utf-8")

    def fail(*_args, **_kwargs):
        raise InstallError("simulated manifest failure")

    monkeypatch.setattr(installer, "write_manifest", fail)
    assert _run(project, config, "install", "--agent", "claude,kilo", "nested_rules") == 4

    assert "simulated manifest failure" in capsys.readouterr().err
    assert settings.read_text(encoding="utf-8") == '{"env": {}}'
    assert not (project / ".claude" / "hooks" / "nested_rules.py").exists()
    assert not (project / ".kilo" / "plugin" / "nested_rules.ts").exists()
    assert not (project / ".skill-tools" / "transaction.json").exists()
    assert not any((project / ".skill-tools" / "backups").glob("*"))


def test_interrupted_file_transaction_is_rolled_back(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".skill-tools" / "backups").mkdir(parents=True)
    (project / "keep.json").write_text("new", encoding="utf-8")
    (project / ".skill-tools" / "backups" / "b1").write_text("old", encoding="utf-8")
    (project / "created.py").write_text("created", encoding="utf-8")
    import hashlib

    journal = {
        "schemaVersion": 2,
        "phase": "applying",
        "manifestBefore": None,
        "operations": [
            {
                "kind": "file",
                "target": "keep.json",
                "backup": ".skill-tools/backups/b1",
                "hadTarget": True,
                "newHash": None,
                "applied": True,
            },
            {
                "kind": "file",
                "target": "created.py",
                "backup": None,
                "hadTarget": False,
                "newHash": hashlib.sha256(b"created").hexdigest(),
                "applied": True,
            },
        ],
    }
    (project / ".skill-tools" / "transaction.json").write_text(
        json.dumps(journal), encoding="utf-8"
    )

    installer.recover_transaction(project)

    assert (project / "keep.json").read_text(encoding="utf-8") == "old"
    assert not (project / "created.py").exists()
    assert not (project / ".skill-tools" / "transaction.json").exists()
