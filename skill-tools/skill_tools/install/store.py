"""The global store that link installs point at.

A link install copies each skill once into the store and places a junction
(Windows) or directory symlink (elsewhere) in the project. The store keeps one
copy per source identity x canonical ID, so updating that copy updates every
project that links to it.

The store reuses the ordinary installer: its root acts as an install root with
``<store>/.skill-tools`` as the state directory, so staging, replacement,
journal recovery and drift checks all come from ``installer`` / ``manifest``.
Each entry lives at ``<sourceKey>/<sha256(canonicalId)[:8]>/<bundleName>``.

Projects are scattered and cannot be scanned, so ``referrers.json`` records
which project path links to which entry. ``collect_garbage`` re-checks those
records and removes entries nothing links to any more; nothing else deletes
store entries.

Store operations take the store lock, project operations take the project
lock, and the two are never held together (store first, then project).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

from ..config import SkillToolsConfig
from ..fs_links import is_link_like, same_link_target, same_path
from ..models import ConfigError, InstallError, SkillBundle
from .installer import (
    InstallPlan,
    _project_install_lock,
    execute_link_install,
    execute_install_locked,
    execute_remove_locked,
    load_project_manifest,
    recover_transaction,
)
from .manifest import MANIFEST_RELATIVE_PATH, _safe_relative, link_store_root, verify_entry

REFERRERS_FILE = "referrers.json"
REFERRERS_SCHEMA_VERSION = 1
GC_GRACE_SECONDS = 3600
"""A referrer younger than this survives GC even before its link exists.

Taking a store entry and creating the project link are separate transactions
(store lock, then project lock), so a concurrent ``store gc`` must not remove an
entry in that window.
"""

_UNSAFE_KEY_CHARS = re.compile(r"[^a-z0-9._-]+")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_key(descriptor: Mapping[str, str]) -> str:
    """Directory name for a source identity (the same elements ``update-skills`` compares).

    Local sources hash the resolved absolute path (case-folded on Windows, where
    paths are case-insensitive). GitHub sources keep a readable owner/repository
    and hash the exact owner/repository/ref, so identities that differ only in
    case still get different directories on a case-insensitive file system.
    """

    source_type = descriptor.get("type")
    if source_type == "local":
        raw = descriptor.get("path")
        if not raw:
            raise InstallError("local source descriptor has no path")
        path = os.path.normcase(str(Path(raw).expanduser().resolve()))
        return f"local-{_sha256(path)[:12]}"
    if source_type == "github":
        owner, repository, ref = (descriptor.get(key) for key in ("owner", "repository", "ref"))
        if not owner or not repository or not ref:
            raise InstallError("GitHub source descriptor needs owner, repository and ref")
        readable = "-".join(
            _UNSAFE_KEY_CHARS.sub("_", part.casefold()).strip("._") or "_"
            for part in (owner, repository)
        )
        return f"github-{readable}-{_sha256(f'{owner}/{repository}@{ref}')[:8]}"
    raise InstallError(f"unsupported source type for the store: {source_type!r}")


def entry_relative_path(descriptor: Mapping[str, str], bundle: SkillBundle) -> str:
    """Store-relative POSIX path of one skill's entry."""

    return "/".join((source_key(descriptor), _sha256(bundle.canonical_id)[:8], bundle.name))


@dataclass(frozen=True)
class Referrer:
    """One project path that links to a store entry."""

    project_root: Path
    install_path: str
    """Project-relative POSIX path of the link."""
    canonical_id: str
    store_path: str
    """Store-relative POSIX path of the entry the link points at."""
    added_at: float = 0.0

    @property
    def link(self) -> Path:
        return self.project_root.joinpath(*PurePosixPath(self.install_path).parts)

    def key(self) -> tuple[str, str]:
        return (
            os.path.normcase(os.path.normpath(str(self.project_root))),
            self.install_path.casefold(),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "projectRoot": str(self.project_root),
            "installPath": self.install_path,
            "canonicalId": self.canonical_id,
            "storePath": self.store_path,
            "addedAt": self.added_at,
        }


def _referrer_from_json(value: object) -> Referrer:
    keys = {"projectRoot", "installPath", "canonicalId", "storePath", "addedAt"}
    if not isinstance(value, dict) or set(value) != keys:
        raise InstallError("store referrers file contains an invalid record")
    root = value["projectRoot"]
    if not isinstance(root, str) or not root or not Path(root).is_absolute():
        raise InstallError("store referrer projectRoot must be an absolute path")
    if not isinstance(value["canonicalId"], str) or not value["canonicalId"]:
        raise InstallError("store referrer has an invalid canonicalId")
    added_at = value["addedAt"]
    if isinstance(added_at, bool) or not isinstance(added_at, (int, float)):
        raise InstallError("store referrer has an invalid addedAt")
    return Referrer(
        project_root=Path(root),
        install_path=_safe_relative(value["installPath"], "referrer install").as_posix(),
        canonical_id=value["canonicalId"],
        store_path=_safe_relative(value["storePath"], "referrer store").as_posix(),
        added_at=float(added_at),
    )


@dataclass(frozen=True)
class StoreEntry:
    """A store entry as ``ensure`` / ``list_entries`` report it."""

    canonical_id: str
    store_path: str
    path: Path
    entry: dict[str, Any]
    referrers: tuple[Referrer, ...] = ()


@dataclass(frozen=True)
class GcResult:
    removed: tuple[StoreEntry, ...]
    pruned_referrers: tuple[Referrer, ...]


@dataclass(frozen=True)
class Store:
    """The store root; its state lives in ``<root>/.skill-tools`` like a project's."""

    root: Path

    @classmethod
    def from_config(cls, config: SkillToolsConfig) -> Store:
        return cls(config.store.path)

    def __post_init__(self) -> None:
        if not self.root.is_absolute():
            raise ConfigError(f"store.path must be absolute: {self.root}")
        object.__setattr__(self, "root", Path(os.path.normpath(self.root)))

    @property
    def state_dir(self) -> Path:
        return self.root / MANIFEST_RELATIVE_PATH.parent

    @property
    def referrers_path(self) -> Path:
        return self.state_dir / REFERRERS_FILE

    # -- location checks ---------------------------------------------------

    def contains(self, path: Path) -> bool:
        """True when ``path`` is the store root or lies inside it (lexically and resolved)."""

        candidates = {Path(os.path.abspath(path))}
        try:
            candidates.add(path.resolve())
        except OSError:
            pass
        root = self.root.resolve() if self.root.exists() else self.root
        for candidate in candidates:
            for base in {self.root, root}:
                if same_path(candidate, base) or os.path.normcase(str(candidate)).startswith(
                    os.path.normcase(str(base)).rstrip("\\/") + os.sep
                ):
                    return True
        return False

    def ensure_outside(self, path: Path, label: str) -> None:
        """Refuse a project path (root or install destination) inside the store."""

        if self.contains(path):
            raise ConfigError(f"{label} lies inside the skill store {self.root}: {path}")

    def _prepare_root(self) -> Path:
        if is_link_like(self.root):
            raise InstallError(f"skill store must not be a symlink or junction: {self.root}")
        if self.root.exists() and not self.root.is_dir():
            raise InstallError(f"skill store is not a directory: {self.root}")
        self.root.mkdir(parents=True, exist_ok=True)
        resolved = self.root.resolve()
        if not same_path(resolved, self.root):
            raise InstallError(f"skill store path has a linked ancestor: {self.root} -> {resolved}")
        return resolved

    def _lock(self):
        return _project_install_lock(self.root, state_dir=self.state_dir)

    # -- referrers ----------------------------------------------------------

    def _load_referrers(self) -> list[Referrer]:
        path = self.referrers_path
        if is_link_like(path):
            raise InstallError(f"store referrers file must not be a symlink: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InstallError(f"store referrers file is unreadable: {path}: {exc}") from exc
        if (
            not isinstance(raw, dict)
            or set(raw) != {"schemaVersion", "referrers"}
            or raw["schemaVersion"] != REFERRERS_SCHEMA_VERSION
            or not isinstance(raw["referrers"], list)
        ):
            raise InstallError(
                f"store referrers file is invalid or from a newer skill-tools: {path}"
            )
        return [_referrer_from_json(item) for item in raw["referrers"]]

    def _write_referrers(self, referrers: Sequence[Referrer]) -> None:
        path = self.referrers_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        payload = {
            "schemaVersion": REFERRERS_SCHEMA_VERSION,
            "referrers": [item.to_json() for item in referrers],
        }
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise InstallError(f"could not write store referrers file: {exc}") from exc

    def _referrer_alive(self, referrer: Referrer, now: float, grace: float) -> bool:
        target = self.root.joinpath(*PurePosixPath(referrer.store_path).parts)
        if same_link_target(referrer.link, target):
            return True
        # Not linked (yet): keep a fresh record whose link may still be on its way.
        return not os.path.lexists(referrer.link) and now - referrer.added_at < grace

    # -- entries ------------------------------------------------------------

    def _entries_by_path(self) -> dict[str, dict[str, Any]]:
        manifest = load_project_manifest(self.root, state_dir=self.state_dir)
        return {entry["installPath"].casefold(): entry for entry in manifest["entries"]}

    def ensure(
        self,
        source,
        bundles: Sequence[SkillBundle],
        *,
        referrers: Iterable[Referrer] = (),
        refresh: bool = False,
        force: bool = False,
    ) -> tuple[StoreEntry, ...]:
        """Make sure each bundle has a store entry and record new referrers.

        A missing entry is copied in. An existing one is kept as is unless
        ``refresh`` re-copies it from ``source`` (``update-skills`` on a link
        entry: every project linking to it sees the change). Existing entries
        are drift-checked first; ``force`` accepts drift when refreshing.
        Referrers (whose ``store_path`` must name one of these entries) are
        recorded in the same store transaction, so ``collect_garbage`` cannot
        remove a fresh entry before its first referrer exists.
        """

        root = self._prepare_root()
        relative = {
            bundle.canonical_id: entry_relative_path(source.descriptor, bundle)
            for bundle in bundles
        }
        if len(set(path.casefold() for path in relative.values())) != len(bundles):
            raise InstallError("selected skills map to the same store entry")
        new_referrers = list(referrers)
        known = {path.casefold() for path in relative.values()}
        for referrer in new_referrers:
            if referrer.store_path.casefold() not in known:
                raise InstallError(
                    f"referrer names an entry that is not being ensured: {referrer.store_path}"
                )
        try:
            with self._lock():
                recover_transaction(root, state_dir=self.state_dir)
                existing = self._entries_by_path()
                to_copy: list[InstallPlan] = []
                managed: list[dict[str, Any]] = []
                for bundle in bundles:
                    target = root.joinpath(*PurePosixPath(relative[bundle.canonical_id]).parts)
                    entry = existing.get(relative[bundle.canonical_id].casefold())
                    if entry is not None:
                        verify_entry(root, entry, force=force and refresh)
                        if not refresh:
                            continue
                        managed.append(entry)
                    to_copy.append(
                        InstallPlan(bundle=bundle, target=target, target_name=None, overwrite=True)
                    )
                if to_copy:
                    execute_install_locked(
                        source,
                        tuple(to_copy),
                        root,
                        overwrite=True,
                        managed_entries=tuple(managed),
                        force_managed=force,
                        state_dir=self.state_dir,
                    )
                if new_referrers:
                    now = time.time()
                    stamped = [
                        Referrer(
                            project_root=Path(os.path.normpath(item.project_root)),
                            install_path=item.install_path,
                            canonical_id=item.canonical_id,
                            store_path=item.store_path,
                            added_at=now,
                        )
                        for item in new_referrers
                    ]
                    replaced = {item.key() for item in stamped}
                    kept = [item for item in self._load_referrers() if item.key() not in replaced]
                    self._write_referrers([*kept, *stamped])
                entries = self._entries_by_path()
                all_referrers = self._load_referrers()
        except InstallError as exc:
            if isinstance(exc.__cause__, PermissionError):
                raise InstallError(
                    f"{exc}; another process (such as an agent reading the skill) may have a "
                    "file in the store open; close it and retry"
                ) from exc
            raise
        except OSError as exc:
            raise InstallError(f"could not update the skill store: {exc}") from exc
        return tuple(
            self._store_entry(entries[relative[bundle.canonical_id].casefold()], all_referrers)
            for bundle in bundles
        )

    def _store_entry(self, entry: dict[str, Any], referrers: Sequence[Referrer]) -> StoreEntry:
        path = entry["installPath"]
        return StoreEntry(
            canonical_id=entry["canonicalId"],
            store_path=path,
            path=self.root.joinpath(*PurePosixPath(path).parts),
            entry=entry,
            referrers=tuple(
                item for item in referrers if item.store_path.casefold() == path.casefold()
            ),
        )

    def list_entries(self) -> tuple[StoreEntry, ...]:
        """Every store entry with its recorded referrers (records are not re-checked)."""

        if not self.root.is_dir():
            return ()
        with self._lock():
            recover_transaction(self.root, state_dir=self.state_dir)
            entries = self._entries_by_path()
            referrers = self._load_referrers()
        return tuple(
            self._store_entry(entry, referrers)
            for entry in sorted(entries.values(), key=lambda item: item["installPath"])
        )

    def referrer_count(self, store_path: str) -> int:
        return sum(
            1
            for entry in self.list_entries()
            if entry.store_path.casefold() == store_path.casefold()
            for _ in entry.referrers
        )

    def record_referrers(self, referrers: Iterable[Referrer]) -> None:
        """Record referrers for entries that already exist (others are skipped).

        Used to put back the records of links a failed project transaction left
        in place; new entries get their first referrer through ``ensure``.
        """

        items = list(referrers)
        if not items or not self.root.is_dir():
            return
        with self._lock():
            recover_transaction(self.root, state_dir=self.state_dir)
            existing = self._entries_by_path()
            now = time.time()
            stamped = [
                replace(item, project_root=Path(os.path.normpath(item.project_root)), added_at=now)
                for item in items
                if item.store_path.casefold() in existing
            ]
            if not stamped:
                return
            replaced = {item.key() for item in stamped}
            kept = [item for item in self._load_referrers() if item.key() not in replaced]
            self._write_referrers([*kept, *stamped])

    def remove_referrers(self, project_root: Path, install_paths: Iterable[str]) -> None:
        """Forget the records for links a project removed (the entries stay until GC)."""

        if not self.referrers_path.exists():
            return
        root = Path(os.path.normpath(project_root))
        dropped = {Referrer(root, path, "", "", 0.0).key() for path in install_paths}
        with self._lock():
            current = self._load_referrers()
            kept = [item for item in current if item.key() not in dropped]
            if len(kept) != len(current):
                self._write_referrers(kept)

    def collect_garbage(
        self, *, dry_run: bool = False, grace_seconds: float = GC_GRACE_SECONDS
    ) -> GcResult:
        """Drop stale referrer records, then remove entries no live record points at.

        A record is live while its project path is still a link to that entry
        (or it is younger than ``grace_seconds`` and its link does not exist
        yet). Drifted entries make the removal stop rather than delete edits.
        """

        if not self.root.is_dir():
            return GcResult((), ())
        root = self._prepare_root()
        try:
            with self._lock():
                recover_transaction(root, state_dir=self.state_dir)
                now = time.time()
                referrers = self._load_referrers()
                alive = [
                    item for item in referrers if self._referrer_alive(item, now, grace_seconds)
                ]
                pruned = tuple(item for item in referrers if item not in alive)
                used = {item.store_path.casefold() for item in alive}
                entries = self._entries_by_path()
                unused = tuple(
                    self._store_entry(entry, ())
                    for key, entry in sorted(entries.items())
                    if key not in used
                )
                if not dry_run:
                    if unused:
                        execute_remove_locked(
                            root,
                            tuple(item.entry for item in unused),
                            state_dir=self.state_dir,
                        )
                        _remove_empty_parents(root, [item.path for item in unused])
                    if pruned:
                        self._write_referrers(alive)
        except InstallError:
            raise
        except OSError as exc:
            raise InstallError(f"could not clean up the skill store: {exc}") from exc
        return GcResult(unused, pruned)


def _remove_empty_parents(root: Path, paths: Iterable[Path]) -> None:
    """Remove the now-empty ``<sourceKey>/<hash>`` directories left by removed entries."""

    for path in paths:
        current = path.parent
        while current != root and current.is_relative_to(root):
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent


def install_links(
    store: Store,
    source,
    plan: Sequence[InstallPlan],
    project_root: Path,
    *,
    overwrite: bool,
    state_dir: Path | None = None,
) -> tuple[InstallPlan, ...]:
    """Link install: ensure the store entries, then place the links in the project.

    Two transactions, never nested: the store (entries + referrer records) under
    the store lock, then the links and the project manifest under the project
    lock. If the project step fails, the referrer records it added are taken
    back and the records of links it left in place are restored; a record that
    survives anyway is harmless (``collect_garbage`` drops it once its grace
    period is over and no link exists).
    """

    root = project_root.resolve()
    store.ensure_outside(root, "project root")
    for item in plan:
        # The parent: an existing link at the target would resolve into the store.
        store.ensure_outside(item.target.parent, "skill destination")
    with _project_install_lock(root, state_dir=state_dir):
        recover_transaction(root, state_dir=state_dir)
        before = load_project_manifest(root, state_dir=state_dir)["entries"]
    previous = {entry["installPath"].casefold(): entry for entry in before}

    bundles: dict[str, SkillBundle] = {}
    for item in plan:
        bundles.setdefault(item.bundle.canonical_id, item.bundle)
    relative = {
        canonical_id: entry_relative_path(source.descriptor, bundle)
        for canonical_id, bundle in bundles.items()
    }
    install_paths = [item.target.relative_to(root).as_posix() for item in plan]
    referrers = [
        Referrer(
            project_root=root,
            install_path=install_path,
            canonical_id=item.bundle.canonical_id,
            store_path=relative[item.bundle.canonical_id],
        )
        for item, install_path in zip(plan, install_paths, strict=True)
    ]
    entries = {
        entry.canonical_id: entry
        for entry in store.ensure(source, tuple(bundles.values()), referrers=referrers)
    }
    link_plan = tuple(
        replace(
            item,
            mode="link",
            store_path=entries[item.bundle.canonical_id].store_path,
            link_target=entries[item.bundle.canonical_id].path,
        )
        for item in plan
    )
    try:
        execute_link_install(
            source.descriptor, link_plan, root, overwrite=overwrite, state_dir=state_dir
        )
    except Exception:
        restored: list[Referrer] = []
        for install_path in install_paths:
            old = previous.get(install_path.casefold())
            if old is None or old["mode"] != "link":
                continue
            link = root.joinpath(*PurePosixPath(install_path).parts)
            old_root = link_store_root(link, old)
            if old_root is not None and same_path(old_root, store.root):
                restored.append(Referrer(root, install_path, old["canonicalId"], old["store"]))
        try:
            store.remove_referrers(root, install_paths)
            store.record_referrers(restored)
        except InstallError:
            pass  # stale records are only kept until `store gc` checks them
        raise
    return link_plan
