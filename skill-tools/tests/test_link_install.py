"""Link installs: project links to the shared store, recorded in manifest v3.

Windows places junctions and other platforms directory symlinks; every
assertion here goes through ``is_link_like`` / ``link_target`` so it holds for
both.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skill_tools.catalog import discover_bundles
from skill_tools.cli import main
from skill_tools.config import load_config
from skill_tools.fs_links import (
    create_dir_link,
    is_link_like,
    link_target,
    remove_link,
    same_path,
)
from skill_tools.install import installer
from skill_tools.install.installer import (
    build_plan,
    execute_install,
    load_project_manifest,
    recover_transaction,
)
from skill_tools.install.store import Store, install_links
from skill_tools.models import ConfigError, InstallError
from skill_tools.source import LocalSource


@pytest.fixture
def env(tmp_path: Path, make_repo, write_config):
    source_root = make_repo(tmp_path / "source")
    store_root = (tmp_path / "store").resolve()
    config_file = write_config(
        tmp_path / "skill-tools.yaml", source_root, tmp_path / "cache" / "skill-index.json"
    )
    with config_file.open("a", encoding="utf-8") as stream:
        stream.write(f"store:\n  path: {store_root.as_posix()}\n")
    config = load_config(config_file)
    source = LocalSource(source_root)
    project = tmp_path / "project"
    project.mkdir()
    return {
        "source": source,
        "bundles": {bundle.name: bundle for bundle in discover_bundles(source)},
        "config": config,
        "config_file": config_file,
        "store": Store(store_root),
        "project": project.resolve(),
        "tmp": tmp_path,
    }


def _link(env, project: Path, *names: str, overwrite: bool = False):
    bundles = tuple(env["bundles"][name] for name in names)
    plan = build_plan(project, bundles, env["config"], overwrite)
    return install_links(env["store"], env["source"], plan, project, overwrite=overwrite)


def _entries(project: Path) -> list[dict]:
    return load_project_manifest(project)["entries"]


def _skill(project: Path, name: str = "alpha") -> Path:
    return project / ".claude" / "skills" / name


def test_link_install_places_a_link_to_the_store_and_records_it(env) -> None:
    project, store = env["project"], env["store"]
    (plan,) = _link(env, project, "alpha")

    link = _skill(project)
    assert is_link_like(link)
    assert same_path(link_target(link), plan.link_target)
    assert plan.link_target.is_relative_to(store.root)
    assert (link / "references" / "guide.md").read_text(encoding="utf-8") == "alpha guide\n"

    (entry,) = _entries(project)
    assert entry["mode"] == "link"
    assert entry["files"] == {}
    assert entry["store"] == plan.store_path
    raw = json.loads((project / ".skill-tools" / "manifest.json").read_text(encoding="utf-8"))
    assert raw["schemaVersion"] == 3

    (store_entry,) = store.list_entries()
    assert store_entry.store_path == plan.store_path
    assert [item.install_path for item in store_entry.referrers] == [".claude/skills/alpha"]
    assert store.collect_garbage(dry_run=True).removed == ()


def test_two_projects_share_one_store_entry(env) -> None:
    other = env["tmp"] / "other"
    other.mkdir()
    (first,) = _link(env, env["project"], "alpha")
    (second,) = _link(env, other.resolve(), "alpha")

    assert first.store_path == second.store_path
    assert env["store"].referrer_count(first.store_path) == 2
    assert len(env["store"].list_entries()) == 1


def test_link_install_refuses_an_existing_target_without_overwrite(env) -> None:
    project = env["project"]
    _link(env, project, "alpha")
    with pytest.raises(InstallError, match="already exists"):
        _link(env, project, "alpha")
    assert is_link_like(_skill(project))


def test_link_install_refuses_a_project_inside_the_store(env) -> None:
    inside = env["store"].root / "project"
    inside.mkdir(parents=True)
    with pytest.raises(ConfigError, match="inside the skill store"):
        _link(env, inside.resolve(), "alpha")


def test_remove_drops_only_the_link_and_its_referrer(env, capsys) -> None:
    project, store = env["project"], env["store"]
    (plan,) = _link(env, project, "alpha")

    assert main(["remove-skills", "alpha", "--dry-run"], cwd=project) == 0
    assert "link only" in capsys.readouterr().out
    assert is_link_like(_skill(project))

    assert main(["remove-skills", "alpha"], cwd=project) == 0
    assert not _skill(project).exists() and not is_link_like(_skill(project))
    assert _entries(project) == []
    assert (plan.link_target / "SKILL.md").is_file()  # the store copy stays
    (store_entry,) = store.list_entries()
    assert store_entry.referrers == ()
    assert [item.store_path for item in store.collect_garbage(grace_seconds=0).removed] == [
        plan.store_path
    ]


def test_remove_never_deletes_a_real_directory_in_place_of_the_link(env) -> None:
    project = env["project"]
    _link(env, project, "alpha")
    link = _skill(project)
    remove_link(link)
    link.mkdir()
    (link / "notes.md").write_text("mine\n", encoding="utf-8")

    assert main(["remove-skills", "alpha", "--force"], cwd=project) == 4
    assert (link / "notes.md").read_text(encoding="utf-8") == "mine\n"
    assert len(_entries(project)) == 1


def test_switch_copy_to_link_and_back(env) -> None:
    project, store, config = env["project"], env["store"], env["config"]
    bundles = (env["bundles"]["alpha"],)
    execute_install(env["source"], build_plan(project, bundles, config, False), project)
    assert _entries(project)[0]["mode"] == "copy"

    with pytest.raises(InstallError, match="already exists"):
        _link(env, project, "alpha")
    (plan,) = _link(env, project, "alpha", overwrite=True)
    (entry,) = _entries(project)
    assert entry["mode"] == "link" and is_link_like(_skill(project))

    # Back to a copy through the CLI, which also forgets the store referrer.
    assert (
        main(
            ["install-skills", "--config", str(env["config_file"]), "--overwrite", "alpha"],
            cwd=project,
        )
        == 0
    )
    link = _skill(project)
    assert not is_link_like(link) and (link / "SKILL.md").is_file()
    (entry,) = _entries(project)
    assert entry["mode"] == "copy"
    assert (plan.link_target / "SKILL.md").is_file()  # replacing the link kept the store copy
    assert store.list_entries()[0].referrers == ()


def test_failed_link_install_rolls_back_the_link_and_the_referrer(env, monkeypatch) -> None:
    project, store, config = env["project"], env["store"], env["config"]
    bundles = (env["bundles"]["alpha"],)
    execute_install(env["source"], build_plan(project, bundles, config, False), project)
    before = _entries(project)

    def broken_write(*_args, **_kwargs):
        raise InstallError("disk full")

    # Fail inside the project transaction only (the store also writes manifests).
    monkeypatch.setattr(installer, "make_link_entry", broken_write)
    with pytest.raises(InstallError, match="disk full"):
        _link(env, project, "alpha", overwrite=True)
    monkeypatch.undo()

    target = _skill(project)
    assert not is_link_like(target) and (target / "SKILL.md").is_file()
    assert _entries(project) == before
    assert not (project / ".skill-tools" / "transaction.json").exists()
    assert store.list_entries()[0].referrers == ()


def test_failed_overwrite_of_a_link_restores_its_referrer(env, monkeypatch) -> None:
    project, store = env["project"], env["store"]
    (plan,) = _link(env, project, "alpha")

    def broken_write(*_args, **_kwargs):
        raise InstallError("disk full")

    # Fail inside the project transaction only (the store also writes manifests).
    monkeypatch.setattr(installer, "make_link_entry", broken_write)
    with pytest.raises(InstallError, match="disk full"):
        _link(env, project, "alpha", overwrite=True)
    monkeypatch.undo()

    assert same_path(link_target(_skill(project)), plan.link_target)
    assert [item.install_path for item in store.list_entries()[0].referrers] == [
        ".claude/skills/alpha"
    ]


def test_failed_remove_restores_the_link(env, monkeypatch) -> None:
    project = env["project"]
    (plan,) = _link(env, project, "alpha")

    def broken_write(*_args, **_kwargs):
        raise InstallError("disk full")

    monkeypatch.setattr(installer, "write_manifest", broken_write)
    with pytest.raises(InstallError, match="disk full"):
        installer.execute_remove(project, tuple(_entries(project)))
    monkeypatch.undo()

    assert same_path(link_target(_skill(project)), plan.link_target)
    assert len(_entries(project)) == 1


def _write_journal(project: Path, operations: list[dict]) -> None:
    manifest = project / ".skill-tools" / "manifest.json"
    journal = {
        "schemaVersion": 4,
        "phase": "applying",
        "manifestBefore": manifest.read_text(encoding="utf-8") if manifest.exists() else None,
        "operations": operations,
    }
    path = project / ".skill-tools" / "transaction.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(journal), encoding="utf-8")


def test_recovery_removes_a_link_created_before_the_manifest_was_written(env) -> None:
    project, store = env["project"], env["store"]
    (store_entry,) = store.ensure(env["source"], (env["bundles"]["alpha"],))
    link = _skill(project)
    create_dir_link(link, store_entry.path)
    _write_journal(
        project,
        [
            {
                "kind": "link",
                "target": ".claude/skills/alpha",
                "backup": None,
                "linkTarget": str(store_entry.path),
                "hadTarget": False,
                "replaced": False,
            }
        ],
    )

    recover_transaction(project)
    assert not is_link_like(link) and not link.exists()
    assert (store_entry.path / "SKILL.md").is_file()
    assert not (project / ".skill-tools" / "transaction.json").exists()


def test_recovery_restores_a_moved_directory_behind_a_link(env) -> None:
    project, store = env["project"], env["store"]
    (store_entry,) = store.ensure(env["source"], (env["bundles"]["alpha"],))
    skills = project / ".claude" / "skills"
    backup = skills / ".alpha.skill-tools-backup-x"
    backup.mkdir(parents=True)
    (backup / "SKILL.md").write_text("old\n", encoding="utf-8")
    create_dir_link(skills / "alpha", store_entry.path)
    _write_journal(
        project,
        [
            {
                "kind": "link",
                "target": ".claude/skills/alpha",
                "backup": ".claude/skills/.alpha.skill-tools-backup-x",
                "linkTarget": str(store_entry.path),
                "hadTarget": True,
                "replaced": True,
            }
        ],
    )

    recover_transaction(project)
    restored = skills / "alpha"
    assert not is_link_like(restored)
    assert (restored / "SKILL.md").read_text(encoding="utf-8") == "old\n"
    assert not backup.exists()


def test_recovery_refuses_a_link_to_somewhere_else(env) -> None:
    project, store = env["project"], env["store"]
    (store_entry,) = store.ensure(env["source"], (env["bundles"]["alpha"],))
    elsewhere = env["tmp"] / "elsewhere"
    elsewhere.mkdir()
    create_dir_link(_skill(project), elsewhere)
    _write_journal(
        project,
        [
            {
                "kind": "link",
                "target": ".claude/skills/alpha",
                "backup": None,
                "linkTarget": str(store_entry.path),
                "hadTarget": False,
                "replaced": False,
            }
        ],
    )

    with pytest.raises(InstallError, match="ambiguous"):
        recover_transaction(project)
    assert is_link_like(_skill(project))


def test_link_operations_need_journal_v4(env) -> None:
    project = env["project"]
    _write_journal(project, [{"kind": "link", "target": ".claude/skills/alpha"}])
    path = project / ".skill-tools" / "transaction.json"
    journal = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**journal, "schemaVersion": 3}), encoding="utf-8")
    with pytest.raises(InstallError, match="invalid operation"):
        recover_transaction(project)


def _update(env, project: Path, *args: str) -> int:
    return main(["update-skills", "--config", str(env["config_file"]), *args], cwd=project)


def _edit_source(env, text: str) -> None:
    skill = env["source"].root / "plugins" / "one" / "skills" / "alpha" / "references"
    (skill / "guide.md").write_text(text, encoding="utf-8")


def test_update_refreshes_the_shared_store_entry_for_every_project(env, capsys) -> None:
    other = (env["tmp"] / "other").resolve()
    other.mkdir()
    _link(env, env["project"], "alpha")
    _link(env, other, "alpha")
    _edit_source(env, "new guide\n")
    capsys.readouterr()

    assert _update(env, env["project"], "alpha", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "would update\tplugins/one/skills/alpha/SKILL.md\t.claude/skills/alpha" in out
    assert "2 link(s)" in out
    guide = _skill(other) / "references" / "guide.md"
    assert guide.read_text(encoding="utf-8") == "alpha guide\n"

    assert _update(env, env["project"], "alpha") == 0
    assert guide.read_text(encoding="utf-8") == "new guide\n"  # the other project follows
    assert is_link_like(_skill(env["project"])) and is_link_like(_skill(other))
    assert _entries(env["project"])[0]["mode"] == "link"  # update keeps the mode


def test_update_refuses_store_drift_unless_forced(env) -> None:
    (plan,) = _link(env, env["project"], "alpha")
    (plan.link_target / "SKILL.md").write_text("edited in the store\n", encoding="utf-8")

    assert _update(env, env["project"]) == 4
    assert (plan.link_target / "SKILL.md").read_text(encoding="utf-8") == "edited in the store\n"
    assert _update(env, env["project"], "--force") == 0
    assert (plan.link_target / "SKILL.md").read_text(encoding="utf-8") != "edited in the store\n"


def test_update_recreates_a_missing_store_entry_only_with_force(env) -> None:
    project, store = env["project"], env["store"]
    (plan,) = _link(env, project, "alpha")
    moved = plan.link_target.with_name("gone")
    plan.link_target.rename(moved)

    assert _update(env, project) == 4
    assert _update(env, project, "--force") == 0
    assert (_skill(project) / "SKILL.md").is_file()
    (store_entry,) = [item for item in store.list_entries() if item.path == plan.link_target]
    assert [item.install_path for item in store_entry.referrers] == [".claude/skills/alpha"]


def test_update_refuses_a_link_into_another_store(env) -> None:
    project = env["project"]
    _link(env, project, "alpha")
    text = env["config_file"].read_text(encoding="utf-8")
    new_store = (env["tmp"] / "moved-store").resolve()
    env["config_file"].write_text(
        text.replace(env["store"].root.as_posix(), new_store.as_posix()), encoding="utf-8"
    )

    assert _update(env, project) == 4
    assert not new_store.exists()


def test_update_refreshes_once_for_links_in_several_targets(env) -> None:
    project = env["project"]
    config_text = env["config_file"].read_text(encoding="utf-8")
    env["config_file"].write_text(
        config_text
        + "targets:\n  claude:\n    destination: .claude/skills\n"
        + "  agents:\n    destination: .agents/skills\n",
        encoding="utf-8",
    )
    config = load_config(env["config_file"])
    plan = build_plan(
        project, (env["bundles"]["alpha"],), config, False, targets=("claude", "agents")
    )
    links = install_links(env["store"], env["source"], plan, project, overwrite=False)
    assert links[0].store_path == links[1].store_path
    _edit_source(env, "both\n")

    assert _update(env, project) == 0
    for root in (".claude/skills", ".agents/skills"):
        guide = project / root / "alpha" / "references" / "guide.md"
        assert guide.read_text(encoding="utf-8") == "both\n"
    assert env["store"].referrer_count(links[0].store_path) == 2
