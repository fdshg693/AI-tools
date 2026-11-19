from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from skill_tools.catalog import discover_bundles
from skill_tools.config import load_config
from skill_tools.fs_links import create_dir_link, remove_link
from skill_tools.install.store import (
    Referrer,
    Store,
    entry_relative_path,
    source_key,
)
from skill_tools.models import ConfigError, InstallError
from skill_tools.source import LocalSource


@pytest.fixture
def setup(tmp_path: Path, make_repo):
    source_root = make_repo(tmp_path / "source")
    source = LocalSource(source_root)
    bundles = {bundle.name: bundle for bundle in discover_bundles(source)}
    store = Store((tmp_path / "store").resolve())
    return source_root, source, bundles, store


def _link_project(store_entry, project: Path, name: str) -> Referrer:
    install_path = f".claude/skills/{name}"
    create_dir_link(project / install_path, store_entry.path)
    return Referrer(
        project_root=project.resolve(),
        install_path=install_path,
        canonical_id=store_entry.canonical_id,
        store_path=store_entry.store_path,
    )


def _referrer(project: Path, name: str, store_entry) -> Referrer:
    return Referrer(
        project_root=project.resolve(),
        install_path=f".claude/skills/{name}",
        canonical_id=store_entry.canonical_id,
        store_path=store_entry.store_path,
    )


def test_source_key_for_local_and_github(tmp_path: Path) -> None:
    local = source_key({"type": "local", "path": str(tmp_path)})
    assert local.startswith("local-") and len(local) == len("local-") + 12
    assert source_key({"type": "local", "path": str(tmp_path / "x" / "..")}) == local
    if sys.platform == "win32":
        assert source_key({"type": "local", "path": str(tmp_path).upper()}) == local

    main = {
        "type": "github",
        "owner": "Owner",
        "repository": "AI.repo",
        "ref": "main",
        "commit": "a",
    }
    key = source_key(main)
    assert key.startswith("github-owner-ai.repo-")
    # The commit is not part of the identity: a newer commit is the same entry.
    assert source_key({**main, "commit": "b"}) == key
    assert source_key({**main, "ref": "dev"}) != key
    # Same folded name, different identity: still a different directory.
    assert source_key({**main, "owner": "owner"}) != key
    with pytest.raises(InstallError):
        source_key({"type": "ftp"})


def test_entry_relative_path_layout(setup) -> None:
    _, source, bundles, _ = setup
    path = entry_relative_path(source.descriptor, bundles["alpha"])
    key, digest, name = path.split("/")
    assert key == source_key(source.descriptor)
    assert len(digest) == 8 and name == "alpha"


def test_store_from_config_uses_store_path(tmp_path: Path) -> None:
    config_file = tmp_path / "skill-tools.yaml"
    config_file.write_text("store:\n  path: my-store\n", encoding="utf-8")
    store = Store.from_config(load_config(config_path=config_file))
    assert store.root == (tmp_path / "my-store").resolve()
    assert store.state_dir == store.root / ".skill-tools"


def test_ensure_copies_once_and_refresh_updates_every_link(setup, tmp_path: Path) -> None:
    source_root, source, bundles, store = setup
    (entry,) = store.ensure(source, [bundles["alpha"]])

    assert entry.path.is_dir() and not os.path.islink(entry.path)
    assert entry.path.is_relative_to(store.root)
    assert (entry.path / "references" / "guide.md").read_text(encoding="utf-8") == "alpha guide\n"
    manifest = json.loads((store.state_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [item["installPath"] for item in manifest["entries"]] == [entry.store_path]
    assert manifest["entries"][0]["source"]["path"] == str(source_root.resolve())

    project_a, project_b = tmp_path / "a", tmp_path / "b"
    _link_project(entry, project_a, "alpha")
    _link_project(entry, project_b, "alpha")

    guide = source_root / "plugins" / "one" / "skills" / "alpha" / "references" / "guide.md"
    guide.write_text("new guide\n", encoding="utf-8")
    store.ensure(source, [bundles["alpha"]])  # an existing entry is reused as is
    assert (entry.path / "references" / "guide.md").read_text(encoding="utf-8") == "alpha guide\n"

    store.ensure(source, [bundles["alpha"]], refresh=True)
    for project in (project_a, project_b):
        linked = project / ".claude" / "skills" / "alpha" / "references" / "guide.md"
        assert linked.read_text(encoding="utf-8") == "new guide\n"


def test_ensure_refuses_drift_unless_refresh_with_force(setup) -> None:
    _, source, bundles, store = setup
    (entry,) = store.ensure(source, [bundles["alpha"]])
    (entry.path / "SKILL.md").write_text("edited\n", encoding="utf-8")

    with pytest.raises(InstallError, match="modified"):
        store.ensure(source, [bundles["alpha"]])
    with pytest.raises(InstallError, match="modified"):
        store.ensure(source, [bundles["alpha"]], refresh=True)
    with pytest.raises(InstallError, match="modified"):
        store.ensure(source, [bundles["alpha"]], force=True)  # force alone never re-copies

    store.ensure(source, [bundles["alpha"]], refresh=True, force=True)
    assert (entry.path / "SKILL.md").read_text(encoding="utf-8") != "edited\n"


def test_ensure_records_and_replaces_referrers(setup, tmp_path: Path) -> None:
    _, source, bundles, store = setup
    store.ensure(source, [bundles["alpha"]])
    (entry,) = store.list_entries()
    referrer = _referrer(tmp_path / "a", "alpha", entry)

    (entry,) = store.ensure(source, [bundles["alpha"]], referrers=[referrer])
    (entry,) = store.ensure(source, [bundles["alpha"]], referrers=[referrer])
    assert len(entry.referrers) == 1
    assert entry.referrers[0].added_at > 0
    assert store.referrer_count(entry.store_path) == 1

    other = Referrer(tmp_path / "a", ".claude/skills/beta", "x", "local-0/00000000/beta")
    with pytest.raises(InstallError, match="not being ensured"):
        store.ensure(source, [bundles["alpha"]], referrers=[other])

    store.remove_referrers(tmp_path / "a", [".claude/skills/alpha"])
    assert store.referrer_count(entry.store_path) == 0


def test_gc_removes_only_entries_without_live_links(setup, tmp_path: Path) -> None:
    _, source, bundles, store = setup
    alpha, beta = store.ensure(source, [bundles["alpha"], bundles["beta"]])
    kept = _link_project(alpha, tmp_path / "a", "alpha")
    gone = _link_project(beta, tmp_path / "b", "beta")
    store.ensure(source, [bundles["alpha"], bundles["beta"]], referrers=[kept, gone])

    # The project dropped its link (e.g. deleted by hand): the record is stale.
    remove_link(gone.link)
    preview = store.collect_garbage(dry_run=True, grace_seconds=0)
    assert [item.canonical_id for item in preview.removed] == [beta.canonical_id]
    assert beta.path.is_dir()

    result = store.collect_garbage(grace_seconds=0)
    assert [item.canonical_id for item in result.removed] == [beta.canonical_id]
    assert [item.install_path for item in result.pruned_referrers] == [gone.install_path]
    assert not beta.path.exists()
    assert not beta.path.parent.exists()  # the empty <hash> directory is gone too
    assert alpha.path.is_dir()
    assert [entry.canonical_id for entry in store.list_entries()] == [alpha.canonical_id]
    assert (tmp_path / "a" / ".claude" / "skills" / "alpha" / "SKILL.md").is_file()


def test_gc_treats_a_real_directory_or_other_link_as_stale(setup, tmp_path: Path) -> None:
    _, source, bundles, store = setup
    alpha, beta = store.ensure(source, [bundles["alpha"], bundles["beta"]])
    replaced = _referrer(tmp_path / "a", "alpha", alpha)
    replaced.link.mkdir(parents=True)  # a copy install now sits where the link was
    elsewhere = _referrer(tmp_path / "b", "beta", beta)
    create_dir_link(elsewhere.link, alpha.path)  # points at a different entry
    store.ensure(source, [bundles["alpha"], bundles["beta"]], referrers=[replaced, elsewhere])

    result = store.collect_garbage(grace_seconds=0)
    assert {item.canonical_id for item in result.removed} == {
        alpha.canonical_id,
        beta.canonical_id,
    }
    assert replaced.link.is_dir()  # project files are never touched


def test_gc_keeps_a_fresh_referrer_whose_link_is_not_created_yet(setup, tmp_path: Path) -> None:
    _, source, bundles, store = setup
    (alpha,) = store.ensure(source, [bundles["alpha"]])
    pending = _referrer(tmp_path / "a", "alpha", alpha)
    store.ensure(source, [bundles["alpha"]], referrers=[pending])

    assert store.collect_garbage().removed == ()
    assert alpha.path.is_dir()
    assert store.collect_garbage(grace_seconds=0).removed[0].canonical_id == alpha.canonical_id


def test_gc_stops_on_a_drifted_unused_entry(setup) -> None:
    _, source, bundles, store = setup
    (alpha,) = store.ensure(source, [bundles["alpha"]])
    (alpha.path / "SKILL.md").write_text("edited\n", encoding="utf-8")
    with pytest.raises(InstallError, match=r"\(modified: SKILL\.md\)"):
        store.collect_garbage(grace_seconds=0)
    assert alpha.path.is_dir()


def test_gc_and_list_on_a_missing_store(tmp_path: Path) -> None:
    store = Store((tmp_path / "none").resolve())
    assert store.list_entries() == ()
    result = store.collect_garbage()
    assert result.removed == () and result.pruned_referrers == ()
    assert not store.root.exists()


def test_store_root_must_not_be_a_link(setup, tmp_path: Path) -> None:
    _, source, bundles, _ = setup
    real = tmp_path / "real-store"
    real.mkdir()
    create_dir_link(tmp_path / "linked-store", real)
    with pytest.raises(InstallError, match="symlink or junction"):
        Store((tmp_path / "linked-store").absolute()).ensure(source, [bundles["alpha"]])


def test_store_path_must_be_absolute() -> None:
    with pytest.raises(ConfigError, match="absolute"):
        Store(Path("relative"))


def test_corrupt_referrers_file_is_refused(setup) -> None:
    _, source, bundles, store = setup
    store.ensure(source, [bundles["alpha"]])
    store.referrers_path.write_text('{"schemaVersion": 99, "referrers": []}', encoding="utf-8")
    with pytest.raises(InstallError, match="referrers"):
        store.list_entries()


def test_ensure_outside_rejects_paths_inside_the_store(tmp_path: Path) -> None:
    store = Store((tmp_path / "store").resolve())
    store.root.mkdir()
    store.ensure_outside(tmp_path / "project" / ".claude" / "skills", "destination")
    store.ensure_outside(tmp_path / "store-other", "destination")
    for inside in (store.root, store.root / "a" / "b"):
        with pytest.raises(ConfigError, match="inside the skill store"):
            store.ensure_outside(inside, "destination")
    # Reached through a link into the store counts as inside too.
    create_dir_link(tmp_path / "via-link", store.root)
    with pytest.raises(ConfigError, match="inside the skill store"):
        store.ensure_outside(tmp_path / "via-link" / "x", "project root")
