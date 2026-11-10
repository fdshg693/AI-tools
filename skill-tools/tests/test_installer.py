from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

import pytest

from skill_tools.catalog import discover_bundles
from skill_tools.config import IndexConfig, SkillToolsConfig, SourceConfig, load_config
from skill_tools.install.installer import build_plan, execute_install, resolve_install_target
from skill_tools.install.installer import execute_remove, load_project_manifest, recover_transaction
from skill_tools.models import ConfigError, InstallError, SkillBundle, SourceError
from skill_tools.source import LocalSource

DEFAULT_DESTINATION = ".claude/skills"


def _config(destinations: dict[str, str] | None = None) -> SkillToolsConfig:
    return SkillToolsConfig(
        source=SourceConfig(type="github"),
        index=IndexConfig(Path("unused.json")),
        destinations=destinations or {},
    )


def test_default_and_per_skill_destination(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    bundle = SkillBundle(
        canonical_id="plugins/one/skills/alpha/SKILL.md",
        name="alpha",
        directory=PurePosixPath("plugins/one/skills/alpha"),
        files=(PurePosixPath("SKILL.md"),),
    )
    assert resolve_install_target(project, bundle, _config()) == (
        project / DEFAULT_DESTINATION / "alpha"
    )
    (project / "skill-tools.yaml").write_text(
        "skills:\n  plugins/one/skills/alpha/SKILL.md:\n    destination: Docs\n",
        encoding="utf-8",
    )
    assert resolve_install_target(project, bundle, load_config(cwd=project)) == (
        project / "Docs" / "alpha"
    )


def test_staging_failure_preserves_existing_skill(tmp_path: Path, make_repo) -> None:
    source_root = make_repo(tmp_path / "source")
    source = LocalSource(source_root)
    bundles = discover_bundles(source)
    project = tmp_path / "project"
    target = project / ".claude" / "skills" / "alpha"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("old\n", encoding="utf-8")
    plan = build_plan(project, bundles, _config(), overwrite=True)

    class InterruptedSource:
        def read_file(self, path):
            if path.as_posix().endswith("beta/SKILL.md"):
                raise SourceError("network interrupted")
            return source.read_file(path)

    with pytest.raises(SourceError, match="network interrupted"):
        execute_install(InterruptedSource(), plan, project)
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "old\n"


def test_unsafe_bundle_path_and_existing_skill_require_explicit_overwrite(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    unsafe = SkillBundle(
        canonical_id="id",
        name="unsafe",
        directory=PurePosixPath("skills/unsafe"),
        files=(PurePosixPath("../outside"),),
    )
    plan = build_plan(project, (unsafe,), _config(), overwrite=False)
    with pytest.raises(InstallError, match="unsafe"):
        execute_install(object(), plan, project)

    bundle = SkillBundle(
        canonical_id="id",
        name="existing",
        directory=PurePosixPath("skills/existing"),
        files=(PurePosixPath("SKILL.md"),),
    )
    (project / ".claude" / "skills" / "existing").mkdir(parents=True)
    with pytest.raises(InstallError, match="--overwrite"):
        build_plan(project, (bundle,), _config(), overwrite=False)


def test_policy_include_and_excludes_reach_staging(tmp_path: Path, make_repo) -> None:
    source_root = make_repo(tmp_path / "source")
    alpha = source_root / "plugins" / "one" / "skills" / "alpha"
    (alpha / ".env").write_text("SECRET=keep\n", encoding="utf-8")
    cache = alpha / "__pycache__"
    cache.mkdir()
    (cache / "module.pyc").write_bytes(b"cache")
    policy_dir = source_root / "tools" / "skill-tools"
    policy_dir.mkdir(parents=True)
    (policy_dir / ".skill-tools").write_text("include:\n  - .env\n", encoding="utf-8")

    source = LocalSource(source_root)
    project = tmp_path / "project"
    project.mkdir()
    plan = build_plan(project, discover_bundles(source), _config(), overwrite=True)
    execute_install(source, plan, project)

    alpha_target = project / DEFAULT_DESTINATION / "alpha"
    assert (alpha_target / ".env").read_text(encoding="utf-8") == "SECRET=keep\n"
    assert not (alpha_target / "__pycache__").exists()


def test_env_is_not_staged_without_include(tmp_path: Path, make_repo) -> None:
    source_root = make_repo(tmp_path / "source")
    (source_root / "plugins" / "one" / "skills" / "alpha" / ".env").write_text(
        "SECRET=drop\n", encoding="utf-8"
    )
    source = LocalSource(source_root)
    project = tmp_path / "project"
    project.mkdir()
    plan = build_plan(project, discover_bundles(source), _config(), overwrite=True)
    execute_install(source, plan, project)
    assert not (project / DEFAULT_DESTINATION / "alpha" / ".env").exists()


def test_overlapping_targets_are_rejected(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    first = SkillBundle(
        canonical_id="one/SKILL.md",
        name="same",
        directory=PurePosixPath("one"),
        files=(PurePosixPath("SKILL.md"),),
    )
    second = SkillBundle(
        canonical_id="two/SKILL.md",
        name="same",
        directory=PurePosixPath("two"),
        files=(PurePosixPath("SKILL.md"),),
    )
    with pytest.raises(InstallError, match="both replace"):
        build_plan(project, (first, second), _config(), overwrite=False)


def test_destination_escape_is_rejected(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    bundle = SkillBundle(
        canonical_id="id",
        name="alpha",
        directory=PurePosixPath("alpha"),
        files=(PurePosixPath("SKILL.md"),),
    )
    with pytest.raises(ConfigError):
        resolve_install_target(project, bundle, _config({"id": "../outside"}))


def test_install_cannot_overwrite_managed_metadata_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    bundle = SkillBundle(
        canonical_id="id",
        name="alpha",
        directory=PurePosixPath("alpha"),
        files=(PurePosixPath("SKILL.md"),),
    )

    with pytest.raises(InstallError, match="managed metadata"):
        build_plan(project, (bundle,), _config({"id": ".skill-tools"}), overwrite=False)


def test_multi_target_install_creates_each_target_copy(tmp_path: Path, make_repo) -> None:
    source_root = make_repo(tmp_path / "source")
    source = LocalSource(source_root)
    bundles = (discover_bundles(source)[0],)
    project = tmp_path / "project"
    project.mkdir()
    config = _config()
    config = config.__class__(
        source=config.source,
        index=config.index,
        destinations=config.destinations,
        targets={"claude": ".claude/skills", "agents": ".agents/skills"},
    )

    plan = build_plan(project, bundles, config, overwrite=False, targets=("claude", "agents"))
    execute_install(source, plan, project)

    assert (project / ".claude" / "skills" / "alpha" / "SKILL.md").is_file()
    assert (project / ".agents" / "skills" / "alpha" / "SKILL.md").is_file()


def test_multi_target_preflight_rejects_case_insensitive_path_collision(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = _config()
    config = config.__class__(
        source=config.source,
        index=config.index,
        destinations=config.destinations,
        targets={"one": "Skills", "two": "skills"},
    )
    bundle = SkillBundle(
        canonical_id="id",
        name="alpha",
        directory=PurePosixPath("alpha"),
        files=(PurePosixPath("SKILL.md"),),
    )

    with pytest.raises(InstallError, match="both replace"):
        build_plan(project, (bundle,), config, overwrite=False, targets=("one", "two"))


def test_later_target_failure_rolls_back_earlier_target(tmp_path: Path, make_repo) -> None:
    source_root = make_repo(tmp_path / "source")
    source = LocalSource(source_root)
    bundle = discover_bundles(source)[0]
    project = tmp_path / "project"
    project.mkdir()
    config = _config()
    config = config.__class__(
        source=config.source,
        index=config.index,
        destinations=config.destinations,
        targets={"first": "first", "second": "second"},
    )
    plan = build_plan(project, (bundle,), config, overwrite=False, targets=("first", "second"))

    original_rename = Path.rename

    def fail_second_incoming(path: Path, target: Path):
        if target == project / "second" / "alpha":
            raise OSError("injected target failure")
        return original_rename(path, target)

    Path.rename = fail_second_incoming
    try:
        with pytest.raises(InstallError, match="injected target failure"):
            execute_install(source, plan, project)
    finally:
        Path.rename = original_rename

    assert not (project / "first" / "alpha").exists()


def test_execute_revalidates_destination_symlinks_under_lock(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    destination = project / "skills"
    destination.mkdir()
    bundle = SkillBundle(
        canonical_id="id",
        name="alpha",
        directory=PurePosixPath("alpha"),
        files=(PurePosixPath("SKILL.md"),),
    )
    plan = build_plan(project, (bundle,), _config({"id": "skills"}), overwrite=False)
    destination.rmdir()
    destination.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ConfigError, match="outside the project"):
        execute_install(object(), plan, project)

    assert not (outside / "alpha").exists()


def test_successful_install_records_each_target_in_manifest(tmp_path: Path, make_repo) -> None:
    source_root = make_repo(tmp_path / "source")
    source = LocalSource(source_root)
    project = tmp_path / "project"
    project.mkdir()
    bundle = discover_bundles(source)[0]
    config = _config()
    config = config.__class__(
        source=config.source,
        index=config.index,
        destinations=config.destinations,
        targets={"claude": ".claude/skills", "agents": ".agents/skills"},
    )
    plan = build_plan(project, (bundle,), config, overwrite=False, targets=("claude", "agents"))

    execute_install(source, plan, project)

    manifest = load_project_manifest(project)
    assert len(manifest["entries"]) == 2
    assert {entry["target"] for entry in manifest["entries"]} == {"claude", "agents"}
    assert all(entry["files"]["SKILL.md"] for entry in manifest["entries"])


def test_interrupted_transaction_is_rolled_back_on_recovery(tmp_path: Path) -> None:
    from skill_tools.install.installer import _journal_path, _write_journal

    project = tmp_path / "project"
    target = project / ".claude" / "skills" / "alpha"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_bytes(b"new\n")
    journal = {
        "schemaVersion": 1,
        "phase": "applying",
        "manifestBefore": None,
        "operations": [
            {
                "target": ".claude/skills/alpha",
                "incoming": ".claude/skills/.alpha-incoming",
                "backup": ".claude/skills/.alpha-backup",
                "hadTarget": False,
                "replaced": False,
                "newFiles": {"SKILL.md": hashlib.sha256(b"new\n").hexdigest()},
            }
        ],
    }
    _write_journal(_journal_path(project), journal)

    recover_transaction(project)

    assert not target.exists()
    assert not _journal_path(project).exists()


def test_manifest_write_failure_rolls_back_installed_directories(
    tmp_path: Path, make_repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skill_tools.install import installer

    source = LocalSource(make_repo(tmp_path / "source"))
    project = tmp_path / "project"
    project.mkdir()
    plan = build_plan(project, (discover_bundles(source)[0],), _config(), overwrite=False)

    def fail_write(*args, **kwargs):
        raise InstallError("manifest write failed")

    monkeypatch.setattr(installer, "write_manifest", fail_write)
    with pytest.raises(InstallError, match="manifest write failed"):
        execute_install(source, plan, project)

    assert not (project / DEFAULT_DESTINATION / "alpha").exists()
    assert not (project / ".skill-tools" / "manifest.json").exists()
    assert not (project / ".skill-tools" / "transaction.json").exists()


def test_remove_manifest_write_failure_restores_managed_directory(
    tmp_path: Path, make_repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skill_tools.install import installer

    source = LocalSource(make_repo(tmp_path / "source"))
    project = tmp_path / "project"
    project.mkdir()
    plan = build_plan(project, (discover_bundles(source)[0],), _config(), overwrite=False)
    execute_install(source, plan, project)
    target = project / DEFAULT_DESTINATION / "alpha"
    entries = tuple(load_project_manifest(project)["entries"])

    def fail_write(*args, **kwargs):
        raise InstallError("manifest write failed")

    monkeypatch.setattr(installer, "write_manifest", fail_write)
    with pytest.raises(InstallError, match="manifest write failed"):
        execute_remove(project, entries)

    assert (target / "SKILL.md").is_file()
    assert len(load_project_manifest(project)["entries"]) == 1
    assert not (project / ".skill-tools" / "transaction.json").exists()
