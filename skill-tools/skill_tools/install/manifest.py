"""Project-local records for skill bundles and hooks installed by skill-tools.

Schema v2 adds a ``hooks`` array next to the skill ``entries``. Schema v3 adds
``mode`` to every skill entry (``copy`` or ``link``) and, for a link entry, the
store-relative ``store`` path of the store entry its link points at. A link
entry's ``files`` is empty: the store's own manifest holds the hashes. v1 and
v2 files are still read (their entries are copies) and are upgraded to v3 on
the next write, so every writer must carry the other array forward instead of
rebuilding the manifest from one side.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ..models import InstallError, SkillBundle
from ..fs_links import is_link_like, link_target, same_path

MANIFEST_SCHEMA_VERSION = 3
_READABLE_SCHEMA_VERSIONS = (1, 2, 3)
INSTALL_MODES = ("copy", "link")
MANIFEST_RELATIVE_PATH = PurePosixPath(".skill-tools/manifest.json")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def empty_manifest() -> dict[str, Any]:
    return {"schemaVersion": MANIFEST_SCHEMA_VERSION, "entries": [], "hooks": []}


def _safe_relative(value: object, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise InstallError(f"managed manifest has an invalid {label} path")
    path = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        path.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or not path.parts
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise InstallError(
            f"managed manifest {label} path must stay inside the install root: {value!r}"
        )
    if path.as_posix() != value:
        raise InstallError(f"managed manifest {label} path is not canonical: {value!r}")
    return path


def _validate_entry(value: object) -> dict[str, Any]:
    required = {
        "canonicalId",
        "bundleName",
        "target",
        "destination",
        "installPath",
        "source",
        "files",
    }
    if (
        not isinstance(value, dict)
        or not required <= set(value)
        or not set(value) - required <= {"mode", "store"}
    ):
        raise InstallError("managed manifest contains an invalid entry")
    mode = value.get("mode", "copy")
    if mode not in INSTALL_MODES:
        raise InstallError(f"managed manifest entry has an invalid mode: {mode!r}")
    for key in ("canonicalId", "bundleName"):
        if not isinstance(value[key], str) or not value[key]:
            raise InstallError(f"managed manifest entry has an invalid {key}")
    name = value["bundleName"]
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise InstallError("managed manifest bundleName must be a directory name")
    target = value["target"]
    if target is not None and (not isinstance(target, str) or not target):
        raise InstallError("managed manifest entry has an invalid target")

    destination = _safe_relative(value["destination"], "destination")
    install_path = _safe_relative(value["installPath"], "install")
    if install_path.parts[0].casefold() == ".skill-tools":
        raise InstallError("managed install path overlaps skill-tools metadata")
    if install_path.name != name or install_path.parent != destination:
        raise InstallError(
            "managed manifest install path does not match its destination and bundle"
        )

    _validate_source(value["source"])

    files = value["files"]
    store: str | None = None
    if mode == "link":
        if "store" not in value:
            raise InstallError("managed manifest link entry has no store path")
        store_path = _safe_relative(value["store"], "store")
        if store_path.name != name or len(store_path.parts) < 2:
            raise InstallError("managed manifest store path does not match its bundle")
        store = store_path.as_posix()
        if files != {}:
            raise InstallError("managed manifest link entry must not record files")
    elif "store" in value:
        raise InstallError("managed manifest copy entry must not have a store path")
    elif not isinstance(files, dict) or not files:
        raise InstallError("managed manifest entry has an invalid files mapping")
    validated_files: dict[str, str] = {}
    for relative, digest in files.items():
        file_path = _safe_relative(relative, "file")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise InstallError(f"managed manifest has an invalid SHA-256 for {relative!r}")
        validated_files[file_path.as_posix()] = digest
    validated = {
        **{key: item for key, item in value.items() if key != "store"},
        "destination": destination.as_posix(),
        "installPath": install_path.as_posix(),
        "files": validated_files,
        "mode": mode,
    }
    if store is not None:
        validated["store"] = store
    return validated


def _validate_source(source: object) -> dict[str, str]:
    valid_source = isinstance(source, dict) and all(
        isinstance(key, str) and key and isinstance(item, str) and item
        for key, item in source.items()
    )
    if valid_source:
        source_type = source.get("type")
        valid_source = (set(source) == {"type", "path"} and source_type == "local") or (
            set(source) == {"type", "owner", "repository", "ref", "commit"}
            and source_type == "github"
        )
    if not valid_source:
        raise InstallError("managed manifest entry has an invalid source descriptor")
    return dict(source)


def _validate_registration(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"file", "event", "matcher", "sha256"}:
        raise InstallError("managed manifest hook entry has an invalid registration")
    if not isinstance(value["event"], str) or not value["event"]:
        raise InstallError("managed manifest hook registration has an invalid event")
    matcher = value["matcher"]
    if matcher is not None and (not isinstance(matcher, str) or not matcher):
        raise InstallError("managed manifest hook registration has an invalid matcher")
    if not isinstance(value["sha256"], str) or not _SHA256.fullmatch(value["sha256"]):
        raise InstallError("managed manifest hook registration has an invalid SHA-256")
    return {**value, "file": _safe_relative(value["file"], "hook registration").as_posix()}


def _validate_hook_entry(value: object) -> dict[str, Any]:
    required = {"hookId", "agent", "installDir", "files", "seedFiles", "registrations", "source"}
    if not isinstance(value, dict) or set(value) != required:
        raise InstallError("managed manifest contains an invalid hook entry")
    for key in ("hookId", "agent"):
        if not isinstance(value[key], str) or not value[key]:
            raise InstallError(f"managed manifest hook entry has an invalid {key}")
    install_dir = _safe_relative(value["installDir"], "hook install")
    if install_dir.parts[0].casefold() == ".skill-tools":
        raise InstallError("managed hook install directory overlaps skill-tools metadata")
    files = value["files"]
    if not isinstance(files, dict) or not files:
        raise InstallError("managed manifest hook entry has an invalid files mapping")
    validated_files: dict[str, str] = {}
    for relative, digest in files.items():
        file_path = _safe_relative(relative, "hook file")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise InstallError(f"managed manifest has an invalid SHA-256 for {relative!r}")
        validated_files[file_path.as_posix()] = digest
    seeds = value["seedFiles"]
    if not isinstance(seeds, list):
        raise InstallError("managed manifest hook entry has an invalid seedFiles list")
    registrations = value["registrations"]
    if not isinstance(registrations, list):
        raise InstallError("managed manifest hook entry has an invalid registrations list")
    return {
        **value,
        "installDir": install_dir.as_posix(),
        "files": validated_files,
        "seedFiles": [_safe_relative(item, "hook seed").as_posix() for item in seeds],
        "registrations": [_validate_registration(item) for item in registrations],
        "source": _validate_source(value["source"]),
    }


def hook_file_paths(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """Project-relative POSIX paths of the files a hook entry owns (seeds excluded)."""

    return tuple(f"{entry['installDir']}/{relative}" for relative in entry["files"])


def validate_manifest(value: object) -> dict[str, Any]:
    """Validate a v1, v2 or v3 manifest and return it in the current (v3) shape."""

    if not isinstance(value, dict) or "schemaVersion" not in value:
        raise InstallError("managed manifest must contain schemaVersion and entries")
    version = value["schemaVersion"]
    if type(version) is not int or version not in _READABLE_SCHEMA_VERSIONS:
        raise InstallError(
            f"managed manifest schema version is unsupported: {version!r} "
            "(it may have been written by a newer skill-tools; update skill-tools)"
        )
    expected_keys = {"schemaVersion", "entries"} | ({"hooks"} if version >= 2 else set())
    if set(value) != expected_keys:
        raise InstallError(
            f"managed manifest v{version} must contain exactly {', '.join(sorted(expected_keys))}"
        )
    entries = value["entries"]
    if not isinstance(entries, list):
        raise InstallError("managed manifest entries must be a list")
    if version < 3 and any(
        isinstance(entry, dict) and ({"mode", "store"} & set(entry)) for entry in entries
    ):
        raise InstallError(f"managed manifest v{version} entries must not have mode or store")
    validated = [_validate_entry(entry) for entry in entries]
    identities = [entry["installPath"].casefold() for entry in validated]
    if len(identities) != len(set(identities)):
        raise InstallError("managed manifest contains duplicate entries")
    for index, path in enumerate(identities):
        for other in identities[index + 1 :]:
            if path.startswith(other.rstrip("/") + "/") or other.startswith(path.rstrip("/") + "/"):
                raise InstallError("managed manifest entries contain overlapping install paths")

    hooks_raw = value.get("hooks", [])
    if not isinstance(hooks_raw, list):
        raise InstallError("managed manifest hooks must be a list")
    hooks = [_validate_hook_entry(entry) for entry in hooks_raw]
    keys = [(entry["hookId"], entry["agent"]) for entry in hooks]
    if len(keys) != len(set(keys)):
        raise InstallError("managed manifest contains duplicate hook entries")
    hook_paths = [path.casefold() for entry in hooks for path in hook_file_paths(entry)]
    if len(hook_paths) != len(set(hook_paths)):
        raise InstallError("managed manifest hook entries share an installed file")
    for path in hook_paths:
        if any(path.startswith(skill.rstrip("/") + "/") for skill in identities):
            raise InstallError("managed manifest hook file lies inside a managed skill")
    return {"schemaVersion": MANIFEST_SCHEMA_VERSION, "entries": validated, "hooks": hooks}


def load_manifest(path: Path) -> dict[str, Any]:
    """Load and fully validate a manifest, treating absence as no managed installs."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty_manifest()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError(f"managed manifest is unreadable or invalid: {path}: {exc}") from exc
    return validate_manifest(raw)


def normalized_source(
    source: Mapping[str, str], project_root: Path, *, relativize: bool = True
) -> dict[str, str]:
    """Record a local source path relative to the project when it lies inside it.

    ``relativize=False`` (the global scope) always keeps the absolute path: the
    install root there is the home directory, not a project the source belongs to.
    """

    normalized = dict(source)
    if normalized.get("type") == "local" and normalized.get("path") and not relativize:
        normalized["path"] = str(Path(normalized["path"]).expanduser().resolve())
    elif normalized.get("type") == "local" and normalized.get("path"):
        source_path = Path(normalized["path"]).expanduser().resolve()
        try:
            normalized["path"] = source_path.relative_to(project_root.resolve()).as_posix()
        except ValueError:
            normalized["path"] = str(source_path)
    return normalized


def make_entry(
    *,
    canonical_id: str,
    bundle_name: str,
    target_name: str | None,
    destination: str,
    install_path: Path,
    project_root: Path,
    source_descriptor: Mapping[str, str],
    bundle: SkillBundle,
    relativize_source: bool = True,
) -> dict[str, Any]:
    project = project_root.resolve()
    target = install_path.resolve()
    if not target.is_relative_to(project):
        raise InstallError(f"managed install path resolves outside the project: {install_path}")
    files: dict[str, str] = {}
    for relative in bundle.files:
        safe = _safe_relative(relative.as_posix(), "bundle file")
        path = target.joinpath(*safe.parts)
        if is_link_like(path) or not path.is_file():
            raise InstallError(f"installed bundle file is missing or a symlink: {path}")
        files[safe.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    entry = {
        "canonicalId": canonical_id,
        "bundleName": bundle_name,
        "target": target_name,
        "destination": destination.replace("\\", "/"),
        "installPath": target.relative_to(project).as_posix(),
        "source": normalized_source(source_descriptor, project, relativize=relativize_source),
        "files": files,
    }
    return _validate_entry(entry)


def make_link_entry(
    *,
    canonical_id: str,
    bundle_name: str,
    target_name: str | None,
    destination: str,
    install_path: Path,
    project_root: Path,
    source_descriptor: Mapping[str, str],
    store_path: str,
    relativize_source: bool = True,
) -> dict[str, Any]:
    """A link entry for the link at ``install_path`` (its last component is not resolved)."""

    project = project_root.resolve()
    parent = install_path.parent.resolve()
    if not parent.is_relative_to(project):
        raise InstallError(f"managed install path resolves outside the project: {install_path}")
    link = parent / install_path.name
    if not is_link_like(link):
        raise InstallError(f"installed skill link is missing: {link}")
    entry = {
        "canonicalId": canonical_id,
        "bundleName": bundle_name,
        "target": target_name,
        "destination": destination.replace("\\", "/"),
        "installPath": link.relative_to(project).as_posix(),
        "source": normalized_source(source_descriptor, project, relativize=relativize_source),
        "files": {},
        "mode": "link",
        "store": store_path,
    }
    return _validate_entry(entry)


def link_install_path(project_root: Path, entry: Mapping[str, Any]) -> Path:
    """Project path of an entry without following its last component (the link itself).

    Every ancestor inside the project must be a real directory, as for
    ``resolve_install_path``; only the final component may be a link.
    """

    relative = _safe_relative(entry.get("installPath"), "install")
    root = project_root.resolve()
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if is_link_like(current):
            raise InstallError(f"managed install path contains a symlink: {current}")
    parent = current.resolve()
    if not parent.is_relative_to(root):
        raise InstallError(f"managed install path resolves outside the project: {current}")
    return parent / relative.name


def link_store_root(link: Path, entry: Mapping[str, Any]) -> Path | None:
    """The store root a link entry's link points into, or None when it is not such a link.

    The link must point at ``<store root>/<entry store path>``; the store root
    is what remains after stripping the recorded store path from the target.
    """

    target = link_target(link)
    store = entry.get("store")
    if target is None or not isinstance(store, str):
        return None
    parts = PurePosixPath(store).parts
    base = target
    for _ in parts:
        base = base.parent
    if not same_path(target, base.joinpath(*parts)):
        return None
    return base


def verify_link_entry(
    project_root: Path,
    entry: Mapping[str, Any],
    *,
    store_root: Path | None = None,
    force: bool = False,
) -> Path:
    """Check a link entry's link and return its (unresolved) project path.

    Drift is: the path is not a link, the link points somewhere other than the
    recorded store entry (under ``store_root`` when given), or the store entry
    directory is gone. Only the last one is accepted by ``force``: skill-tools
    holds no hashes for a real directory in place of the link, so it cannot
    tell whether the files there belong to the user.
    """

    validated = _validate_entry(dict(entry))
    if validated["mode"] != "link":
        raise InstallError(f"managed entry is not a link: {validated['installPath']}")
    link = link_install_path(project_root, validated)
    if not os.path.lexists(link):
        raise InstallError(f"managed skill link is missing: {link}")
    if not is_link_like(link):
        raise InstallError(
            f"managed skill link was replaced by a real directory or file: {link}; "
            "skill-tools does not know whether its contents are yours, so move or delete "
            "it by hand (--force does not remove it)"
        )
    base = link_store_root(link, validated)
    if base is None:
        raise InstallError(
            f"managed skill link points at {link_target(link)}, not at the recorded store "
            f"entry {validated['store']}: {link}"
        )
    if store_root is not None and not same_path(base, store_root):
        raise InstallError(
            f"managed skill link points into {base}, not into the configured skill store "
            f"{store_root} (store.path changed?): {link}"
        )
    if not force and not base.joinpath(*PurePosixPath(validated["store"]).parts).is_dir():
        raise InstallError(f"managed skill link points at a missing store entry: {link}")
    return link


def verify_managed_entry(
    project_root: Path,
    entry: Mapping[str, Any],
    *,
    store_root: Path | None = None,
    force: bool = False,
) -> Path:
    """``verify_entry`` for a copy entry, ``verify_link_entry`` for a link entry."""

    if entry.get("mode", "copy") == "link":
        return verify_link_entry(project_root, entry, store_root=store_root, force=force)
    return verify_entry(project_root, entry, force=force)


def resolve_install_path(project_root: Path, entry: Mapping[str, Any]) -> Path:
    relative = _safe_relative(entry.get("installPath"), "install")
    root = project_root.resolve()
    path = root.joinpath(*relative.parts)
    # Reject every symlink component, including a symlinked ancestor directory.
    current = root
    for part in relative.parts:
        current = current / part
        if is_link_like(current):
            raise InstallError(f"managed install path contains a symlink: {current}")
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise InstallError(f"managed install path resolves outside the project: {path}")
    return resolved


def verify_entry(project_root: Path, entry: Mapping[str, Any], *, force: bool = False) -> Path:
    """Reject filesystem drift unless force explicitly accepts managed-directory changes."""

    validated = _validate_entry(dict(entry))
    if validated["mode"] != "copy":
        raise InstallError(f"managed entry is a link, not a copy: {validated['installPath']}")
    target = resolve_install_path(project_root, validated)
    if not target.is_dir():
        raise InstallError(f"managed installation is missing: {target}")
    actual: set[str] = set()
    for current, dirs, files in os.walk(target, followlinks=False):
        current_path = Path(current)
        for name in [*dirs, *files]:
            child = current_path / name
            if is_link_like(child):
                raise InstallError(f"managed installation contains a symlink: {child}")
        for name in files:
            actual.add((current_path / name).relative_to(target).as_posix())
    expected = set(validated["files"])
    if not force and actual - expected:
        raise InstallError(f"managed installation contains extra files: {target}")
    if not force and expected - actual:
        raise InstallError(f"managed installation has missing files: {target}")
    if not force:
        for relative, expected_hash in validated["files"].items():
            digest = hashlib.sha256(
                (target / Path(*PurePosixPath(relative).parts)).read_bytes()
            ).hexdigest()
            if digest != expected_hash:
                raise InstallError(f"managed installation has modified files: {target / relative}")
    return target


def write_manifest(path: Path, value: Mapping[str, Any]) -> None:
    """Validate then atomically replace a manifest in its own directory."""

    validated = validate_manifest(dict(value))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(validated, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise InstallError(f"could not atomically write managed manifest: {exc}") from exc
