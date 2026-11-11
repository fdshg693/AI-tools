"""Install, update, and remove catalog hooks in a project, recorded in the manifest.

With ``global_scope`` the root is the home directory: files go to the
user-wide hook directories, the user-wide registration files are edited, and
command lines use absolute paths (see ``registrars``).

One call to ``apply_hook_changes`` plans every file write/delete (hook files,
seed configs, agent registration files) against the current disk state and
then commits them together with the manifest through the shared project lock
and journal. Updates are "remove the old entry, install the new one" in a
single transaction, so an interrupted update rolls back to the old hook.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import HooksConfig
from .registrars import (
    RegistrationDocument,
    build_entry,
    command_path,
    entry_hash,
    install_dir_for,
    registration_file_for,
    supports_global,
)
from .catalog import AGENTS
from ..install.installer import (
    _project_install_lock,
    execute_file_transaction,
    load_project_manifest,
    recover_transaction,
)
from ..install.manifest import hook_file_paths, normalized_source
from ..models import CatalogError, ConfigError, HookAgent, HookRecord, InstallError
from ..source import LocalSource
from ..fs_links import is_link_like


@dataclass(frozen=True)
class HookTarget:
    """One hook delivered to one agent at a project-relative directory."""

    hook: HookRecord
    spec: HookAgent
    install_dir: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.hook.id, self.spec.agent)


@dataclass
class HookChangeSet:
    """What a hooks command did (or would do with --dry-run)."""

    actions: list[tuple[str, ...]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_agents(value: str | None, config: HooksConfig) -> tuple[str, ...]:
    """``--agent a,b``; falls back to ``hooks.default_agents`` from the config."""

    if value is None:
        if not config.default_agents:
            raise ConfigError(
                "--agent is required (or set hooks.default_agents in skill-tools.yaml)"
            )
        return config.default_agents
    agents = tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    unknown = [agent for agent in agents if agent not in AGENTS]
    if not agents or unknown:
        raise ConfigError(f"--agent must list agents from: {', '.join(AGENTS)}")
    return agents


def global_agents(agents: Sequence[str], *, explicit: bool) -> tuple[tuple[str, ...], list[str]]:
    """Drop agents without a user-wide hook location for ``--global``.

    An agent named with ``--agent`` is an error; one from ``hooks.default_agents``
    is skipped with a warning.
    """

    unsupported = [agent for agent in agents if not supports_global(agent)]
    if unsupported and explicit:
        raise ConfigError(
            f"--global does not support hooks for {', '.join(unsupported)} "
            "(no known user-wide hook location)"
        )
    warnings = (
        [f"--global does not support hooks for {', '.join(unsupported)}; skipping those agents"]
        if unsupported
        else []
    )
    kept = tuple(agent for agent in agents if supports_global(agent))
    if not kept:
        raise ConfigError("no selected agent supports --global hooks")
    return kept, warnings


def ensure_installable(
    hook: HookRecord, source, project: Path, *, global_scope: bool = False
) -> None:
    """``distributable: false`` hooks may only be installed into their own source repository.

    They are always refused with ``global_scope``: the home directory is never
    the hook's own repository.
    """

    if hook.distributable:
        return
    if global_scope:
        raise CatalogError(
            f"hook {hook.id} is not distributable; it cannot be installed with --global"
        )
    if isinstance(source, LocalSource) and source.root == project.resolve():
        return
    raise CatalogError(
        f"hook {hook.id} is not distributable; it can only be installed into its own "
        "repository (local source whose path is the project root)"
    )


def select_install_targets(
    hooks: Sequence[HookRecord],
    ids: Sequence[str],
    agents: Sequence[str],
    config: HooksConfig,
    source,
    project: Path,
    *,
    global_scope: bool = False,
) -> tuple[tuple[HookTarget, ...], list[str]]:
    by_id = {hook.id: hook for hook in hooks}
    targets: list[HookTarget] = []
    warnings: list[str] = []
    for hook_id in dict.fromkeys(ids):
        hook = by_id.get(hook_id)
        if hook is None:
            raise CatalogError(f"no hook in the catalog matches {hook_id!r}")
        ensure_installable(hook, source, project, global_scope=global_scope)
        supported = [agent for agent in agents if hook.agent(agent) is not None]
        if not supported:
            raise CatalogError(
                f"hook {hook_id} does not support {', '.join(agents)} "
                f"(available: {', '.join(item.agent for item in hook.agents)})"
            )
        unsupported = [agent for agent in agents if agent not in supported]
        if unsupported:
            warnings.append(
                f"hook {hook_id} does not support {', '.join(unsupported)}; skipping those agents"
            )
        for tool in hook.requires_tools:
            if shutil.which(tool) is None:
                warnings.append(
                    f"hook {hook_id} requires the tool {tool!r}, which is not on PATH; "
                    f"install it with `skill-tools install-tools {tool}`"
                )
        targets.extend(
            HookTarget(hook, spec, install_dir_for(agent, config, global_scope=global_scope))
            for agent in supported
            if (spec := hook.agent(agent)) is not None
        )
    return tuple(targets), warnings


def select_managed_hooks(
    entries: Sequence[dict], ids: Sequence[str], agents: Sequence[str] | None
) -> tuple[dict, ...]:
    selected = [entry for entry in entries if agents is None or entry["agent"] in agents]
    if not ids:
        return tuple(selected)
    chosen: list[dict] = []
    for hook_id in ids:
        matches = [entry for entry in selected if entry["hookId"] == hook_id]
        if not matches:
            raise InstallError(f"no managed hook installation matches {hook_id!r}")
        chosen.extend(entry for entry in matches if entry not in chosen)
    return tuple(chosen)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class _Planner:
    def __init__(
        self, project: Path, manifest: dict, config: HooksConfig, *, global_scope: bool = False
    ) -> None:
        self.root = project.resolve()
        self.home = self.root if global_scope else None
        self.manifest = manifest
        self.config = config
        self.changes: dict[str, bytes | None] = {}
        self.documents: dict[str, RegistrationDocument] = {}
        self.planned: set[str] = set()
        self.result = HookChangeSet()

    def document(self, agent: str, relative: str) -> RegistrationDocument:
        key = relative.casefold()
        if key not in self.documents:
            path = self.root / relative
            if is_link_like(path) or (path.exists() and not path.is_file()):
                raise InstallError(f"registration file is not a regular file: {path}")
            raw = path.read_bytes() if path.is_file() else None
            self.documents[key] = RegistrationDocument(agent, relative, raw)
        document = self.documents[key]
        if document.agent != agent:
            raise InstallError(f"{relative} is used as the registration file of two agents")
        return document

    def remove(self, entry: dict, *, force: bool) -> None:
        label = (entry["hookId"], entry["agent"])
        for path, digest in zip(hook_file_paths(entry), entry["files"].values(), strict=True):
            target = self.root / path
            if not target.is_file():
                if not force:
                    raise InstallError(
                        f"managed hook file is missing: {path} (use --force to continue)"
                    )
                self.result.warnings.append(f"managed hook file already missing: {path}")
                continue
            if _sha256(target.read_bytes()) != digest and not force:
                raise InstallError(
                    f"managed hook file was modified: {path} (use --force to replace or delete it)"
                )
            self.changes[path] = None
            self.result.actions.append(("remove", *label, path))
        for registration in entry["registrations"]:
            document = self.document(entry["agent"], registration["file"])
            where = f"{registration['file']} {registration['event']}" + (
                f" [{registration['matcher']}]" if registration["matcher"] else ""
            )
            if document.remove(
                entry["hookId"],
                registration["event"],
                registration["matcher"],
                registration["sha256"],
            ):
                self.result.actions.append(("unregister", *label, where))
            elif force:
                self.result.warnings.append(
                    f"managed registration not found (edited or removed by hand), skipped: {where}"
                )
            else:
                raise InstallError(
                    f"managed registration changed or is missing in {where} "
                    "(use --force to skip it)"
                )

    def install(self, source, target: HookTarget, *, overwrite: bool) -> dict[str, Any]:
        spec = target.spec
        label = target.key
        remaining = [
            entry for entry in self.manifest["hooks"] if (entry["hookId"], entry["agent"]) != label
        ]
        managed_paths = {path.casefold() for entry in remaining for path in hook_file_paths(entry)}
        skill_paths = [entry["installPath"].casefold() for entry in self.manifest["entries"]]
        files: dict[str, str] = {}
        for item in spec.files:
            path = f"{target.install_dir}/{item.install_path.as_posix()}"
            key = path.casefold()
            if key in managed_paths:
                raise InstallError(f"{path} is already managed by another hook installation")
            if any(key.startswith(skill.rstrip("/") + "/") for skill in skill_paths):
                raise InstallError(f"{path} lies inside a managed skill directory")
            if key in self.planned:
                raise InstallError(f"two selected hooks would both write {path}")
            self.planned.add(key)
            destination = self.root / path
            if destination.exists() and path not in self.changes and not overwrite:
                raise InstallError(f"{path} already exists (use --overwrite to replace it)")
            content = source.read_file(item.source_path)
            files[item.install_path.as_posix()] = _sha256(content)
            if destination.is_file() and destination.read_bytes() == content:
                self.changes.pop(path, None)
            else:
                self.changes[path] = content
            self.result.actions.append(("install", *label, path))
        seeds: list[str] = []
        for item in spec.seed_files:
            path = f"{target.install_dir}/{item.install_path.as_posix()}"
            seeds.append(item.install_path.as_posix())
            if (self.root / path).exists() or path in self.changes:
                self.result.actions.append(("keep-seed", *label, path))
                continue
            self.changes[path] = source.read_file(item.source_path)
            self.result.actions.append(("seed", *label, path))
        registrations: list[dict[str, Any]] = []
        relative = registration_file_for(
            spec.agent, self.config, global_scope=self.home is not None
        )
        if relative is not None:
            document = self.document(spec.agent, relative)
            main_path = f"{target.install_dir}/{spec.main.as_posix()}"
            needle = command_path(spec.agent, main_path, self.home)
            owned = {
                registration["sha256"]
                for entry in remaining
                for registration in entry["registrations"]
                if registration["file"].casefold() == relative.casefold()
            }
            for command in document.foreign_commands(needle, owned):
                self.result.warnings.append(
                    f"{relative} already has an unmanaged hook running {needle}; "
                    f"it may run twice: {command.strip()}"
                )
            for registration in spec.registrations:
                entry = build_entry(
                    spec.agent, spec.runner, main_path, registration, home=self.home
                )
                matcher = registration.get("matcher")
                document.add(target.hook.id, registration["event"], matcher, entry)
                registrations.append(
                    {
                        "file": relative,
                        "event": registration["event"],
                        "matcher": matcher,
                        "sha256": entry_hash(entry),
                    }
                )
                where = f"{relative} {registration['event']}" + (f" [{matcher}]" if matcher else "")
                self.result.actions.append(("register", *label, where))
        return {
            "hookId": target.hook.id,
            "agent": spec.agent,
            "installDir": target.install_dir,
            "files": files,
            "seedFiles": seeds,
            "registrations": registrations,
            "source": normalized_source(source.descriptor, self.root, relativize=self.home is None),
        }

    def ensure_documents_unchanged(self) -> None:
        """Stop when a registration file changed on disk since it was read."""

        for document in self.documents.values():
            path = self.root / document.relative
            current = path.read_bytes() if path.is_file() else None
            if current != document.raw:
                raise InstallError(
                    f"{path} changed while skill-tools was editing it (is the agent running?); "
                    "nothing was changed. Close the agent and retry"
                )

    def finish(self) -> list[tuple[str, bytes | None]]:
        for document in self.documents.values():
            if not document.changed:
                continue
            content = document.content()
            if content == document.raw or (content is None and document.raw is None):
                continue
            self.changes[document.relative] = content
        return [
            (path, content)
            for path, content in self.changes.items()
            if content is not None or (self.root / path).exists()
        ]


def apply_hook_changes(
    project: Path,
    *,
    source=None,
    hooks_config: HooksConfig | None = None,
    remove: Sequence[dict] = (),
    install: Sequence[HookTarget] = (),
    overwrite: bool = False,
    force: bool = False,
    dry_run: bool = False,
    state_dir: Path | None = None,
    global_scope: bool = False,
) -> HookChangeSet:
    """Remove managed hook entries and/or install targets as one transaction.

    ``state_dir`` holds the manifest, journal, and file backups; it defaults to
    ``<project>/.skill-tools``. ``global_scope`` treats ``project`` as the home
    directory (user-wide registration files, absolute command lines).
    Registration files are re-read just before writing; if another program
    (e.g. a running agent rewriting ``~/.claude/settings.json``) changed one
    meanwhile, nothing is written.
    """

    root = project.resolve()
    with _project_install_lock(root, state_dir=state_dir):
        recover_transaction(root, state_dir=state_dir)
        manifest = load_project_manifest(root, state_dir=state_dir)
        current = {(entry["hookId"], entry["agent"]): entry for entry in manifest["hooks"]}
        remove_keys = [(entry["hookId"], entry["agent"]) for entry in remove]
        for key, expected in zip(remove_keys, remove, strict=True):
            if current.get(key) != expected:
                raise InstallError("managed manifest changed before the hook change; refusing")
        for target in install:
            if target.key in current and target.key not in remove_keys:
                raise InstallError(
                    f"hook {target.hook.id} is already installed for {target.spec.agent}; "
                    "use `skill-tools hooks update`"
                )
        planner = _Planner(root, manifest, hooks_config or HooksConfig(), global_scope=global_scope)
        for entry in remove:
            planner.remove(entry, force=force)
        kept = [
            entry
            for entry in manifest["hooks"]
            if (entry["hookId"], entry["agent"]) not in set(remove_keys)
        ]
        planner.manifest = {**manifest, "hooks": kept}
        added = [planner.install(source, target, overwrite=overwrite) for target in install]
        changes = planner.finish()
        if not dry_run:
            planner.ensure_documents_unchanged()
            execute_file_transaction(
                root, changes, {**manifest, "hooks": [*kept, *added]}, state_dir=state_dir
            )
    # An update is remove + install of the same key; report it as one line per hook/agent.
    for new in added:
        key = (new["hookId"], new["agent"])
        old = current.get(key) if key in remove_keys else None
        if old is None:
            continue
        same = {k: v for k, v in old.items() if k != "source"} == {
            k: v for k, v in new.items() if k != "source"
        }
        planner.result.actions = [
            action for action in planner.result.actions if (action[1], action[2]) != key
        ]
        planner.result.actions.append(("unchanged" if same else "update", *key, new["installDir"]))
    return planner.result
