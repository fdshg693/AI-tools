from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from skill_tools.install.manifest import (
    empty_manifest,
    load_manifest,
    link_install_path,
    link_store_root,
    make_entry,
    make_link_entry,
    verify_entry,
    verify_link_entry,
    verify_managed_entry,
    write_manifest,
)
from skill_tools.fs_links import create_dir_link, remove_link
from skill_tools.models import InstallError
from skill_tools.models import SkillBundle
from pathlib import PurePosixPath


def test_manifest_round_trip_and_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / ".skill-tools" / "manifest.json"
    data = empty_manifest()

    write_manifest(path, data)

    assert load_manifest(path) == data
    path.write_text('{"schemaVersion":99,"entries":[]}', encoding="utf-8")
    with pytest.raises(InstallError, match="schema"):
        load_manifest(path)


def test_manifest_records_project_relative_files_and_source(tmp_path: Path) -> None:
    root = tmp_path / "project"
    target = root / ".agents" / "skills" / "alpha"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("managed\n", encoding="utf-8")

    entry = make_entry(
        canonical_id="plugins/alpha/SKILL.md",
        bundle_name="alpha",
        target_name="agents",
        destination=".agents/skills",
        install_path=target,
        project_root=root,
        source_descriptor={"type": "local", "path": str(root / "catalog")},
        bundle=SkillBundle(
            canonical_id="plugins/alpha/SKILL.md",
            name="alpha",
            directory=PurePosixPath("plugins/alpha"),
            files=(PurePosixPath("SKILL.md"),),
        ),
    )

    assert entry["installPath"] == ".agents/skills/alpha"
    assert entry["files"]["SKILL.md"]
    assert entry["source"]["path"] == "catalog"
    assert entry["installPath"] == ".agents/skills/alpha"


def test_verify_entry_rejects_modified_missing_and_extra_files(tmp_path: Path) -> None:
    root = tmp_path / "project"
    target = root / ".claude" / "skills" / "alpha"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("original\n", encoding="utf-8")
    entry = make_entry(
        canonical_id="plugins/alpha/SKILL.md",
        bundle_name="alpha",
        target_name=None,
        destination=".claude/skills",
        install_path=target,
        project_root=root,
        source_descriptor={
            "type": "github",
            "owner": "acme",
            "repository": "skills",
            "ref": "main",
            "commit": "abc",
        },
        bundle=SkillBundle(
            canonical_id="plugins/alpha/SKILL.md",
            name="alpha",
            directory=PurePosixPath("plugins/alpha"),
            files=(PurePosixPath("SKILL.md"),),
        ),
    )
    verify_entry(root, entry)

    (target / "notes.txt").write_text("user file\n", encoding="utf-8")
    with pytest.raises(InstallError, match="extra"):
        verify_entry(root, entry)
    verify_entry(root, entry, force=True)
    (target / "notes.txt").unlink()
    (target / "SKILL.md").write_text("edited\n", encoding="utf-8")
    with pytest.raises(InstallError, match="modified"):
        verify_entry(root, entry)
    (target / "SKILL.md").unlink()
    with pytest.raises(InstallError, match="missing"):
        verify_entry(root, entry)


def test_verify_entry_rejects_symlinks_even_with_force(tmp_path: Path) -> None:
    root = tmp_path / "project"
    target = root / ".claude" / "skills" / "alpha"
    target.mkdir(parents=True)
    managed_file = target / "SKILL.md"
    managed_file.write_bytes(b"managed\n")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside\n")
    try:
        (target / "linked.txt").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")
    entry = {
        "canonicalId": "plugins/alpha/SKILL.md",
        "bundleName": "alpha",
        "target": None,
        "destination": ".claude/skills",
        "installPath": ".claude/skills/alpha",
        "source": {"type": "local", "path": "catalog"},
        "files": {"SKILL.md": hashlib.sha256(b"managed\n").hexdigest()},
    }

    with pytest.raises(InstallError, match="symlink"):
        verify_entry(root, entry, force=True)


@pytest.mark.parametrize("install_path", ["../outside/alpha", "C:/outside/alpha", "/outside/alpha"])
def test_load_manifest_rejects_paths_outside_project(install_path: str, tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "entries": [
                    {
                        "canonicalId": "plugins/alpha/SKILL.md",
                        "bundleName": "alpha",
                        "target": None,
                        "destination": ".claude/skills",
                        "installPath": install_path,
                        "source": {"type": "local", "path": "catalog"},
                        "files": {"SKILL.md": "0" * 64},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(InstallError, match="path"):
        load_manifest(path)


def _hook_entry(**overrides) -> dict:
    entry = {
        "hookId": "nested_rules",
        "agent": "claude",
        "installDir": ".claude/hooks",
        "files": {"nested_rules.py": "0" * 64},
        "seedFiles": [],
        "registrations": [
            {"file": ".claude/settings.json", "event": "Stop", "matcher": None, "sha256": "1" * 64}
        ],
        "source": {"type": "local", "path": "catalog"},
    }
    entry.update(overrides)
    return entry


def test_v1_manifest_is_read_and_written_back_as_v3(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text('{"schemaVersion": 1, "entries": []}', encoding="utf-8")

    loaded = load_manifest(path)
    assert loaded == empty_manifest()
    write_manifest(path, {**loaded, "hooks": [_hook_entry()]})
    assert json.loads(path.read_text(encoding="utf-8"))["schemaVersion"] == 3
    assert load_manifest(path)["hooks"][0]["hookId"] == "nested_rules"


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ({"schemaVersion": 4, "entries": [], "hooks": []}, "update skill-tools"),
        ({"schemaVersion": 2, "entries": []}, "must contain exactly"),
        ({"schemaVersion": 1, "entries": [], "hooks": []}, "must contain exactly"),
        (
            {"schemaVersion": 2, "entries": [], "hooks": [_hook_entry(), _hook_entry()]},
            "duplicate hook",
        ),
        (
            {
                "schemaVersion": 2,
                "entries": [],
                "hooks": [_hook_entry(), _hook_entry(agent="codex")],
            },
            "share an installed file",
        ),
        (
            {"schemaVersion": 2, "entries": [], "hooks": [_hook_entry(installDir="../x")]},
            "inside the install root",
        ),
        (
            {"schemaVersion": 2, "entries": [], "hooks": [_hook_entry(registrations=[{}])]},
            "invalid registration",
        ),
        (
            {"schemaVersion": 2, "entries": [], "hooks": [_hook_entry(extra=True)]},
            "invalid hook entry",
        ),
    ],
)
def test_manifest_v2_hook_validation(tmp_path: Path, manifest: dict, message: str) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InstallError, match=message):
        load_manifest(path)


def _skill_entry(**overrides) -> dict:
    entry = {
        "canonicalId": "plugins/alpha/SKILL.md",
        "bundleName": "alpha",
        "target": None,
        "destination": ".claude/skills",
        "installPath": ".claude/skills/alpha",
        "source": {"type": "local", "path": "catalog"},
        "files": {"SKILL.md": "0" * 64},
    }
    entry.update(overrides)
    return entry


def _link_entry(**overrides) -> dict:
    values = {"files": {}, "mode": "link", "store": "local-0123456789ab/01234567/alpha"}
    return _skill_entry(**{**values, **overrides})


def test_v2_copy_entry_gains_mode_and_is_written_as_v3(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"schemaVersion": 2, "entries": [_skill_entry()], "hooks": []}),
        encoding="utf-8",
    )

    loaded = load_manifest(path)
    assert loaded["schemaVersion"] == 3
    assert loaded["entries"][0]["mode"] == "copy"
    assert "store" not in loaded["entries"][0]
    write_manifest(path, loaded)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schemaVersion"] == 3
    assert raw["entries"][0]["mode"] == "copy"


def test_v3_link_entry_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest = {"schemaVersion": 3, "entries": [_link_entry()], "hooks": []}
    write_manifest(path, manifest)
    assert load_manifest(path) == manifest


@pytest.mark.parametrize(
    ("entries", "version", "message"),
    [
        ([_skill_entry(mode="copy")], 2, "must not have mode"),
        ([_link_entry()], 2, "must not have mode"),
        ([_skill_entry(mode="hardlink")], 3, "invalid mode"),
        ([_skill_entry(files={}, mode="link")], 3, "no store path"),
        ([_link_entry(files={"SKILL.md": "0" * 64})], 3, "must not record files"),
        ([_skill_entry(store="local-x/01234567/alpha")], 3, "must not have a store"),
        ([_skill_entry(mode="link", files={}, store="local-x/01234567/beta")], 3, "store path"),
        ([_skill_entry(mode="link", files={}, store="alpha")], 3, "store path"),
        ([_skill_entry(mode="link", files={}, store="../x/alpha")], 3, "store"),
        ([_skill_entry(extra=1)], 3, "invalid entry"),
    ],
)
def test_v3_entry_validation(tmp_path: Path, entries: list, version: int, message: str) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"schemaVersion": version, "entries": entries, "hooks": []}), encoding="utf-8"
    )
    with pytest.raises(InstallError, match=message):
        load_manifest(path)


def _linked_project(tmp_path: Path) -> tuple[Path, Path, dict]:
    project = tmp_path / "project"
    store_root = (tmp_path / "store").resolve()
    entry = _link_entry()
    store_entry = store_root.joinpath(*PurePosixPath(entry["store"]).parts)
    store_entry.mkdir(parents=True)
    (store_entry / "SKILL.md").write_text("store\n", encoding="utf-8")
    create_dir_link(project / ".claude" / "skills" / "alpha", store_entry)
    return project, store_root, entry


def test_make_and_verify_link_entry(tmp_path: Path) -> None:
    project, store_root, expected = _linked_project(tmp_path)
    link = project / ".claude" / "skills" / "alpha"

    entry = make_link_entry(
        canonical_id="plugins/alpha/SKILL.md",
        bundle_name="alpha",
        target_name=None,
        destination=".claude/skills",
        install_path=link,
        project_root=project,
        source_descriptor={"type": "local", "path": str(project / "catalog")},
        store_path=expected["store"],
    )
    assert entry == expected
    assert link_install_path(project, entry) == project.resolve() / ".claude/skills/alpha"
    assert verify_link_entry(project, entry) == link_install_path(project, entry)
    assert verify_link_entry(project, entry, store_root=store_root)
    assert verify_managed_entry(project, entry, store_root=store_root)
    assert link_store_root(link, entry) == store_root
    with pytest.raises(InstallError, match="not a copy"):
        verify_entry(project, entry, force=True)


def test_verify_link_entry_drift(tmp_path: Path) -> None:
    project, store_root, entry = _linked_project(tmp_path)
    link = project / ".claude" / "skills" / "alpha"

    with pytest.raises(InstallError, match="configured skill store"):
        verify_link_entry(project, entry, store_root=tmp_path / "other-store")

    store_entry = store_root.joinpath(*PurePosixPath(entry["store"]).parts)
    moved = store_entry.with_name("moved")
    store_entry.rename(moved)
    with pytest.raises(InstallError, match="missing store entry"):
        verify_link_entry(project, entry)
    # --force accepts the missing store entry (update re-creates it, remove drops the link).
    assert verify_link_entry(project, entry, force=True) == link_install_path(project, entry)
    moved.rename(store_entry)

    remove_link(link)
    create_dir_link(link, moved.parent.parent)  # some other directory
    with pytest.raises(InstallError, match="not at the recorded store entry"):
        verify_link_entry(project, entry, force=True)

    remove_link(link)
    with pytest.raises(InstallError, match="missing"):
        verify_link_entry(project, entry, force=True)

    link.mkdir()
    (link / "SKILL.md").write_text("mine\n", encoding="utf-8")
    with pytest.raises(InstallError, match="real directory"):
        verify_link_entry(project, entry, force=True)
    assert (link / "SKILL.md").read_text(encoding="utf-8") == "mine\n"
