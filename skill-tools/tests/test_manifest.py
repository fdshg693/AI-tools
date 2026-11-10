from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from skill_tools.install.manifest import (
    empty_manifest,
    load_manifest,
    make_entry,
    verify_entry,
    write_manifest,
)
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


def test_v1_manifest_is_read_as_v2_and_written_back_as_v2(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text('{"schemaVersion": 1, "entries": []}', encoding="utf-8")

    loaded = load_manifest(path)
    assert loaded == empty_manifest()
    write_manifest(path, {**loaded, "hooks": [_hook_entry()]})
    assert json.loads(path.read_text(encoding="utf-8"))["schemaVersion"] == 2
    assert load_manifest(path)["hooks"][0]["hookId"] == "nested_rules"


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ({"schemaVersion": 3, "entries": [], "hooks": []}, "update skill-tools"),
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
            "inside the project",
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
