"""Preflight and atomic replacement of selected skill directories."""

from __future__ import annotations

import shutil
import tempfile
import uuid
import hashlib
import os
import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from collections.abc import Iterator, Sequence

from ..config import SkillToolsConfig
from .manifest import (
    MANIFEST_RELATIVE_PATH,
    load_manifest,
    make_entry,
    validate_manifest,
    verify_entry,
    write_manifest,
)
from ..models import ConfigError, InstallError, SkillBundle

# v1 journals hold only directory swaps; v2 adds per-file operations ("kind": "file").
JOURNAL_SCHEMA_VERSIONS = (1, 2)


@dataclass(frozen=True)
class InstallPlan:
    """A selected bundle and its final on-disk directory."""

    bundle: SkillBundle
    target: Path
    target_name: str | None = None
    overwrite: bool = False


def manifest_path(project: Path) -> Path:
    root = project.resolve()
    directory = root / MANIFEST_RELATIVE_PATH.parent
    if directory.is_symlink() or not directory.resolve().is_relative_to(root):
        raise InstallError(f"managed metadata directory is unsafe: {directory}")
    return directory / "manifest.json"


def load_project_manifest(project: Path) -> dict:
    path = manifest_path(project)
    if path.is_symlink():
        raise InstallError(f"managed manifest must not be a symlink: {path}")
    return load_manifest(path)


def _safe_project_path(project: Path, relative: str) -> Path:
    from .manifest import _safe_relative

    path = project.resolve().joinpath(*_safe_relative(relative, "transaction").parts)
    if not path.resolve(strict=False).is_relative_to(project.resolve()):
        raise InstallError(f"transaction path resolves outside the project: {relative}")
    return path


def _journal_path(project: Path) -> Path:
    return manifest_path(project).with_name("transaction.json")


def _write_journal(path: Path, journal: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(journal, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise InstallError(f"could not write managed transaction journal: {exc}") from exc


def _tree_hashes(directory: Path) -> dict[str, str] | None:
    if directory.is_symlink() or not directory.is_dir():
        return None
    hashes: dict[str, str] = {}
    for current, dirs, files in os.walk(directory, followlinks=False):
        current_path = Path(current)
        if any((current_path / name).is_symlink() for name in [*dirs, *files]):
            return None
        for name in files:
            file_path = current_path / name
            hashes[file_path.relative_to(directory).as_posix()] = hashlib.sha256(
                file_path.read_bytes()
            ).hexdigest()
    return hashes


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recover_file_operation(project: Path, operation: dict) -> None:
    """Undo one file-level operation: restore its backup or delete a file it created."""

    target = _safe_project_path(project, operation.get("target"))
    backup_value = operation.get("backup")
    backup = _safe_project_path(project, backup_value) if isinstance(backup_value, str) else None
    if backup is not None and backup.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(backup, target)
    elif not operation.get("hadTarget", False):
        if target.is_file():
            if _file_hash(target) != operation.get("newHash"):
                raise InstallError(
                    f"interrupted transaction target is ambiguous; refusing cleanup: {target}"
                )
            target.unlink()
    elif operation.get("applied"):
        raise InstallError(f"interrupted transaction backup is missing; refusing cleanup: {target}")


def recover_transaction(project: Path) -> None:
    """Roll back an interrupted transaction or finish cleanup after commit."""

    journal_path = _journal_path(project)
    if journal_path.is_symlink():
        raise InstallError(f"managed transaction journal must not be a symlink: {journal_path}")
    if not journal_path.exists():
        return
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError(
            f"managed transaction journal is corrupt; refusing changes: {exc}"
        ) from exc
    if (
        not isinstance(journal, dict)
        or journal.get("schemaVersion") not in JOURNAL_SCHEMA_VERSIONS
        or journal.get("phase") not in {"applying", "committed"}
        or not isinstance(journal.get("operations"), list)
        or not isinstance(journal.get("manifestBefore"), (str, type(None)))
    ):
        raise InstallError(
            "managed transaction journal is invalid or from a newer skill-tools; refusing changes"
        )
    for operation in journal["operations"]:
        if not isinstance(operation, dict) or operation.get("kind", "directory") not in {
            "directory",
            "file",
        }:
            raise InstallError("managed transaction journal contains an invalid operation")

    if journal["phase"] == "committed":
        for operation in journal["operations"]:
            backup = operation.get("backup")
            if isinstance(backup, str):
                _remove_path(_safe_project_path(project, backup))
        journal_path.unlink(missing_ok=True)
        return

    for operation in reversed(journal["operations"]):
        if operation.get("kind") == "file":
            _recover_file_operation(project, operation)
            continue
        target = _safe_project_path(project, operation.get("target"))
        incoming = _safe_project_path(project, operation.get("incoming"))
        backup_value = operation.get("backup")
        backup = (
            _safe_project_path(project, backup_value) if isinstance(backup_value, str) else None
        )
        expected = operation.get("newFiles")
        if not isinstance(expected, dict):
            raise InstallError("managed transaction journal has invalid file hashes")
        if backup is not None and backup.exists():
            _remove_directory(target)
            backup.rename(target)
        elif not operation.get("hadTarget", False) and target.exists():
            if _tree_hashes(target) != expected:
                raise InstallError(
                    f"interrupted transaction target is ambiguous; refusing cleanup: {target}"
                )
            _remove_directory(target)
        elif operation.get("hadTarget", False) and operation.get("replaced"):
            raise InstallError(
                f"interrupted transaction backup is missing; refusing cleanup: {target}"
            )
        _remove_directory(incoming)

    manifest_file = manifest_path(project)
    previous = journal["manifestBefore"]
    if previous is None:
        manifest_file.unlink(missing_ok=True)
    else:
        temporary = manifest_file.with_name(f".{manifest_file.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(previous, encoding="utf-8", newline="\n")
        os.replace(temporary, manifest_file)
    journal_path.unlink(missing_ok=True)


def _safe_destination_parts(destination: str) -> tuple[str, ...]:
    native = Path(destination)
    if not destination or native.is_absolute() or ".." in native.parts:
        raise ConfigError(f"destination must be a safe relative path: {destination!r}")
    return native.parts


def resolve_install_target(
    cwd: Path, bundle: SkillBundle, config: SkillToolsConfig, target_name: str | None = None
) -> Path:
    """Compute the final `<destination>/<skill-name>` directory within cwd."""

    project = cwd.resolve()
    destination = config.destination_for(bundle.canonical_id, target_name)
    destination_root = (project / Path(*_safe_destination_parts(destination))).resolve()
    if not destination_root.is_relative_to(project):
        raise ConfigError(f"destination resolves outside the project: {destination!r}")
    target = (destination_root / bundle.name).resolve()
    if not target.is_relative_to(project):
        raise ConfigError(f"skill target resolves outside the project: {bundle.name!r}")
    return target


def build_plan(
    cwd: Path,
    bundles: tuple[SkillBundle, ...],
    config: SkillToolsConfig,
    overwrite: bool,
    targets: tuple[str, ...] | None = None,
) -> tuple[InstallPlan, ...]:
    """Validate destination mapping before changing any filesystem state."""

    selected_targets = targets
    if selected_targets is not None:
        if not selected_targets or len(set(selected_targets)) != len(selected_targets):
            raise ConfigError("--target requires one or more unique target names")
        unknown = set(selected_targets) - set(config.targets)
        if unknown:
            raise ConfigError(f"unknown target(s): {', '.join(sorted(unknown))}")
    plan = tuple(
        InstallPlan(
            bundle=bundle,
            target=resolve_install_target(cwd, bundle, config, target_name),
            target_name=target_name,
            overwrite=overwrite,
        )
        for bundle in bundles
        for target_name in (selected_targets if selected_targets is not None else (None,))
    )
    targets_seen: set[str] = set()
    metadata_path = (cwd.resolve() / ".skill-tools").as_posix().casefold()
    for item in plan:
        target_key = item.target.as_posix().casefold()
        if target_key == metadata_path or target_key.startswith(metadata_path + "/"):
            raise InstallError(f"skill destination overlaps managed metadata: {item.target}")
        if target_key in targets_seen:
            raise InstallError(
                f"selected skills would both replace {item.target}; select one skill name per destination"
            )
        targets_seen.add(target_key)
        for other in plan:
            if other is item:
                continue
            other_key = other.target.as_posix().casefold()
            if target_key.startswith(other_key.rstrip("/") + "/") or other_key.startswith(
                target_key.rstrip("/") + "/"
            ):
                raise InstallError(
                    f"skill destinations have a file/directory conflict: {item.target}"
                )
        for parent in item.target.parents:
            if parent == cwd.resolve():
                break
            if parent.is_file():
                raise InstallError(f"existing file blocks skill destination: {parent}")
        if item.target.exists() and not item.target.is_dir():
            raise InstallError(f"existing skill target is not a directory: {item.target}")
        if item.target.exists() and not overwrite:
            raise InstallError(
                f"skill already exists: {item.target} (use --overwrite to replace it)"
            )
    return plan


@contextmanager
def _project_install_lock(cwd: Path) -> Iterator[None]:
    """Serialize installs targeting the same resolved project across processes."""

    project_key = str(cwd.resolve()).casefold().encode("utf-8")
    lock_root = Path(tempfile.gettempdir()) / "skill-tools-locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / f"{hashlib.sha256(project_key).hexdigest()}.lock"
    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            if lock_file.read(1) == b"":
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _validate_plan_target(item: InstallPlan, cwd: Path, overwrite: bool) -> None:
    project = cwd.resolve()
    resolved = item.target.resolve()
    if not resolved.is_relative_to(project):
        raise ConfigError(f"destination resolves outside the project: {item.target}")
    if resolved != item.target:
        raise InstallError(f"skill destination changed during installation: {item.target}")
    if item.target.exists() and not item.target.is_dir():
        raise InstallError(f"existing skill target is not a directory: {item.target}")
    if item.target.exists() and not overwrite:
        raise InstallError(f"skill already exists: {item.target} (use --overwrite to replace it)")


def _safe_relative_path(path: PurePosixPath) -> Path:
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise InstallError(f"source bundle contains unsafe path: {path}")
    return Path(*path.parts)


def _write_staging_bundle(source, bundle: SkillBundle, destination: Path) -> None:
    for relative_path in bundle.files:
        local_relative = _safe_relative_path(relative_path)
        output = (destination / local_relative).resolve()
        if not output.is_relative_to(destination.resolve()):
            raise InstallError(f"source bundle path escapes staging directory: {relative_path}")
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            output.write_bytes(source.read_file(bundle.directory / relative_path))
        except OSError as exc:
            raise InstallError(
                f"could not stage {bundle.canonical_id}:{relative_path}: {exc}"
            ) from exc


def _remove_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    """Replace ``path`` via a sibling temporary file so readers never see a partial file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.skill-tools-{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def execute_file_transaction(
    project: Path, changes: Sequence[tuple[str, bytes | None]], manifest: dict
) -> None:
    """Apply file writes/deletes and a manifest update as one recoverable transaction.

    ``changes`` maps project-relative POSIX paths to new content, or ``None`` to
    delete. Unlike skill directories, hooks share their directories (and the
    agents' registration files) with unmanaged files, so every operation backs
    up and restores a single file. The caller must hold the project lock and
    have run ``recover_transaction`` already.
    """

    root = project.resolve()
    manifest_file = manifest_path(root)
    validated = validate_manifest(manifest)
    backups = manifest_file.parent / "backups"
    operations: list[dict] = []
    for relative, content in changes:
        target = _safe_project_path(root, relative)
        current = root
        for part in PurePosixPath(relative).parts:
            current = current / part
            if current.is_symlink():
                raise InstallError(f"managed hook path contains a symlink: {current}")
        if target.exists() and not target.is_file():
            raise InstallError(f"managed hook path is not a regular file: {target}")
        had_target = target.is_file()
        operations.append(
            {
                "kind": "file",
                "target": relative,
                "backup": (backups / uuid.uuid4().hex).relative_to(root).as_posix()
                if had_target
                else None,
                "hadTarget": had_target,
                "newHash": hashlib.sha256(content).hexdigest() if content is not None else None,
                "applied": False,
            }
        )
    journal_file = _journal_path(root)
    journal = {
        "schemaVersion": 2,
        "phase": "applying",
        "manifestBefore": manifest_file.read_text(encoding="utf-8")
        if manifest_file.exists()
        else None,
        "operations": operations,
    }
    _write_journal(journal_file, journal)
    try:
        for (_, content), operation in zip(changes, operations, strict=True):
            target = _safe_project_path(root, operation["target"])
            if operation["backup"] is not None:
                backup = _safe_project_path(root, operation["backup"])
                backup.parent.mkdir(parents=True, exist_ok=True)
                if content is None:
                    os.replace(target, backup)
                else:
                    shutil.copy2(target, backup)
            if content is not None:
                _atomic_write_bytes(target, content)
            elif operation["backup"] is None:
                target.unlink(missing_ok=True)
            operation["applied"] = True
            _write_journal(journal_file, journal)
        write_manifest(manifest_file, validated)
        journal["phase"] = "committed"
        _write_journal(journal_file, journal)
        for operation in operations:
            if operation["backup"] is not None:
                _remove_path(_safe_project_path(root, operation["backup"]))
        journal_file.unlink(missing_ok=True)
    except Exception as exc:
        try:
            recover_transaction(root)
        except Exception as recovery_exc:
            raise InstallError(f"{exc}; transaction recovery stopped: {recovery_exc}") from exc
        if isinstance(exc, InstallError):
            raise
        if isinstance(exc, OSError):
            raise InstallError(f"could not update managed hook files: {exc}") from exc
        raise


def execute_install(
    source,
    plan: tuple[InstallPlan, ...],
    cwd: Path,
    *,
    overwrite: bool | None = None,
    managed_entries: tuple[dict, ...] = (),
    force_managed: bool = False,
) -> None:
    """Stage every bundle, then replace targets with rollback on a later failure."""

    try:
        allow_overwrite = (
            overwrite if overwrite is not None else all(item.overwrite for item in plan)
        )
        with _project_install_lock(cwd):
            recover_transaction(cwd)
            if managed_entries:
                current = load_project_manifest(cwd)["entries"]
                by_path = {entry["installPath"].casefold(): entry for entry in current}
                for expected in managed_entries:
                    entry = by_path.get(expected["installPath"].casefold())
                    if entry != expected:
                        raise InstallError(
                            "managed manifest changed before update; refusing changes"
                        )
                    verify_entry(cwd, entry, force=force_managed)
            for item in plan:
                _validate_plan_target(item, cwd, allow_overwrite)
            _execute_install_locked(source, plan, cwd, allow_overwrite)
    except InstallError:
        raise
    except OSError as exc:
        raise InstallError(f"could not create or update skill directories: {exc}") from exc


def execute_remove(project: Path, entries: tuple[dict, ...], *, force: bool = False) -> None:
    """Remove only verified manifest entries, recording a recoverable transaction."""

    root = project.resolve()
    try:
        with _project_install_lock(root):
            recover_transaction(root)
            manifest = load_project_manifest(root)
            selected_paths = {entry["installPath"].casefold() for entry in entries}
            current = [
                entry
                for entry in manifest["entries"]
                if entry["installPath"].casefold() in selected_paths
            ]
            if len(current) != len(selected_paths):
                raise InstallError("managed manifest changed before remove; refusing changes")
            operations: list[dict] = []
            for entry in current:
                target = verify_entry(root, entry, force=force)
                operations.append(
                    {
                        "target": target.relative_to(root).as_posix(),
                        "incoming": (target.parent / f".{target.name}.unused-{uuid.uuid4().hex}")
                        .relative_to(root)
                        .as_posix(),
                        "backup": (
                            target.parent / f".{target.name}.skill-tools-backup-{uuid.uuid4().hex}"
                        )
                        .relative_to(root)
                        .as_posix(),
                        "hadTarget": True,
                        "replaced": False,
                        "newFiles": {},
                    }
                )
            path = manifest_path(root)
            before = path.read_text(encoding="utf-8") if path.exists() else None
            journal_file = _journal_path(root)
            journal = {
                "schemaVersion": 1,
                "phase": "applying",
                "manifestBefore": before,
                "operations": operations,
            }
            _write_journal(journal_file, journal)
            try:
                for entry, operation in zip(current, operations, strict=True):
                    target = _safe_project_path(root, operation["target"])
                    backup = _safe_project_path(root, operation["backup"])
                    # Re-check after the lock and immediately before moving the directory.
                    verify_entry(root, entry, force=force)
                    target.rename(backup)
                    operation["replaced"] = True
                    _write_journal(journal_file, journal)
                retained = [
                    entry
                    for entry in manifest["entries"]
                    if entry["installPath"].casefold() not in selected_paths
                ]
                write_manifest(path, validate_manifest({**manifest, "entries": retained}))
                journal["phase"] = "committed"
                _write_journal(journal_file, journal)
                for operation in operations:
                    _remove_directory(_safe_project_path(root, operation["backup"]))
                journal_file.unlink(missing_ok=True)
            except Exception as exc:
                try:
                    recover_transaction(root)
                except Exception as recovery_exc:
                    raise InstallError(
                        f"{exc}; transaction recovery stopped: {recovery_exc}"
                    ) from exc
                if isinstance(exc, InstallError):
                    raise
                if isinstance(exc, OSError):
                    raise InstallError(f"could not remove managed skill directory: {exc}") from exc
                raise
    except InstallError:
        raise
    except OSError as exc:
        raise InstallError(f"could not remove managed skill directory: {exc}") from exc


def _execute_install_locked(
    source, plan: tuple[InstallPlan, ...], cwd: Path, overwrite: bool
) -> None:
    root = cwd.resolve()
    manifest_file = manifest_path(root)
    manifest = load_project_manifest(root)
    previous_manifest = (
        manifest_file.read_text(encoding="utf-8") if manifest_file.exists() else None
    )
    journal_file = _journal_path(root)
    operations: list[dict] = []
    for item in plan:
        item.target.parent.mkdir(parents=True, exist_ok=True)
        incoming = (
            item.target.parent / f".{item.target.name}.skill-tools-incoming-{uuid.uuid4().hex}"
        )
        backup = item.target.parent / f".{item.target.name}.skill-tools-backup-{uuid.uuid4().hex}"
        operations.append(
            {
                "target": item.target.relative_to(root).as_posix(),
                "incoming": incoming.relative_to(root).as_posix(),
                "backup": backup.relative_to(root).as_posix(),
                "hadTarget": item.target.exists(),
                "replaced": False,
                "newFiles": {},
            }
        )
    journal = {
        "schemaVersion": 1,
        "phase": "applying",
        "manifestBefore": previous_manifest,
        "operations": operations,
    }
    _write_journal(journal_file, journal)
    try:
        for item, operation in zip(plan, operations, strict=True):
            incoming = _safe_project_path(root, operation["incoming"])
            incoming.mkdir()
            _write_staging_bundle(source, item.bundle, incoming)
            hashes = _tree_hashes(incoming)
            if hashes is None:
                raise InstallError(
                    f"staged skill bundle contains an unsupported symlink: {incoming}"
                )
            operation["newFiles"] = hashes
            _write_journal(journal_file, journal)

        for item, operation in zip(plan, operations, strict=True):
            _validate_plan_target(item, root, overwrite)
            target = item.target
            incoming = _safe_project_path(root, operation["incoming"])
            backup = _safe_project_path(root, operation["backup"])
            if target.exists():
                target.rename(backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            incoming.rename(target)
            operation["replaced"] = True
            _write_journal(journal_file, journal)

        entries = list(manifest["entries"])
        for item in plan:
            entry = make_entry(
                canonical_id=item.bundle.canonical_id,
                bundle_name=item.bundle.name,
                target_name=item.target_name,
                destination=item.target.parent.relative_to(root).as_posix(),
                install_path=item.target,
                project_root=root,
                source_descriptor=source.descriptor,
                bundle=item.bundle,
            )
            entries = [
                old
                for old in entries
                if not (
                    old["canonicalId"] == entry["canonicalId"]
                    and old["installPath"].casefold() == entry["installPath"].casefold()
                )
            ]
            entries.append(entry)
        write_manifest(manifest_file, validate_manifest({**manifest, "entries": entries}))
        journal["phase"] = "committed"
        _write_journal(journal_file, journal)
        for operation in operations:
            _remove_directory(_safe_project_path(root, operation["backup"]))
        journal_file.unlink(missing_ok=True)
    except Exception as exc:
        try:
            recover_transaction(root)
        except Exception as recovery_exc:
            raise InstallError(f"{exc}; transaction recovery stopped: {recovery_exc}") from exc
        if isinstance(exc, InstallError):
            raise
        if isinstance(exc, OSError):
            raise InstallError(f"could not replace skill directory: {exc}") from exc
        raise
