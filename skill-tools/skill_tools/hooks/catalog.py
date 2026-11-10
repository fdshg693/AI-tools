"""Read the distributable hook catalog announced by repo-hooks.yaml.

``repo-hooks.yaml`` at the source root only names where the generated hook
catalog lives (agent-tooling's builder writes it from each scenario's
``hook.yaml``). This module reads that entry point and the catalog through the
configured ``CatalogSource``, so a local clone and a GitHub source both work
without walking the tree. Validation is strict because Step 4 installs from
these records: unknown keys, unsafe paths, and files missing from the source
are errors. A source without ``repo-hooks.yaml`` simply has no hooks.

The hook catalog is independent of the skill catalog: only ``hooks``
subcommands load it, so a broken hook catalog never stops skill commands.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath
from typing import Any

import yaml

from ..models import CatalogError, HookAgent, HookFile, HookRecord, SourceError
from ..source import CatalogSource

REPO_HOOKS_FILENAME = "repo-hooks.yaml"
_REPO_HOOKS_PATH = PurePosixPath(REPO_HOOKS_FILENAME)
CATALOG_SCHEMA_VERSION = 1
AGENTS = ("claude", "codex", "cursor", "antigravity", "kilo")
RUNNERS = ("python", "uv-script", "uv-project")
_HOOK_KEYS = {"id", "description", "distributable", "requiresTools", "agents"}
_AGENT_KEYS = {"runner", "main", "files", "seedFiles", "dependencies", "registrations"}
_FILE_KEYS = {"path", "installPath"}
# Mirrors agent-tooling's builder: tool-specific registration values only. The
# command string is never part of the catalog; the installer builds it.
_REGISTRATION_KEYS = {
    "claude": {"event", "matcher", "timeout", "statusMessage", "async"},
    "codex": {"event", "matcher", "timeout", "statusMessage", "additionalContextLimit"},
    "cursor": {"event", "matcher", "timeout"},
    "antigravity": {"event", "matcher", "timeout"},
    "kilo": set(),
}
_HOOK_ID = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CatalogError(message)


def _check_keys(raw: dict, allowed: set[str], label: str, *, required: bool = True) -> None:
    unknown = set(raw) - allowed
    _require(not unknown, f"{label} contains unknown keys: {', '.join(sorted(unknown))}")
    if required:
        missing = allowed - set(raw)
        _require(not missing, f"{label} is missing keys: {', '.join(sorted(missing))}")


def _safe_path(value: object, label: str) -> PurePosixPath:
    _require(isinstance(value, str) and bool(value), f"{label} must be a non-empty relative path")
    path = PurePosixPath(value)
    _require(
        not path.is_absolute()
        and ".." not in path.parts
        and "." not in path.parts
        and "\\" not in value
        and ":" not in value,
        f"{label} is unsafe: {value!r}",
    )
    return path


def _string_list(value: object, label: str) -> tuple[str, ...]:
    _require(
        isinstance(value, list) and all(isinstance(item, str) and item for item in value),
        f"{label} must be a list of non-empty strings",
    )
    return tuple(value)


def _files(value: object, base: PurePosixPath, label: str) -> tuple[HookFile, ...]:
    _require(isinstance(value, list), f"{label} must be a list")
    files: list[HookFile] = []
    for index, raw in enumerate(value):
        item_label = f"{label}[{index}]"
        _require(isinstance(raw, dict), f"{item_label} must be a mapping")
        _check_keys(raw, _FILE_KEYS, item_label)
        files.append(
            HookFile(
                source_path=base / _safe_path(raw["path"], f"{item_label}.path"),
                install_path=_safe_path(raw["installPath"], f"{item_label}.installPath"),
            )
        )
    install_paths = [item.install_path for item in files]
    _require(len(install_paths) == len(set(install_paths)), f"{label} has duplicate installPath")
    return tuple(files)


def _registrations(value: object, agent: str, label: str) -> tuple[dict[str, Any], ...]:
    _require(isinstance(value, list), f"{label} must be a list")
    if agent == "kilo":
        _require(not value, f"{label} must be empty for kilo (placement enables the plugin)")
        return ()
    _require(bool(value), f"{label} must not be empty")
    registrations: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        item_label = f"{label}[{index}]"
        _require(isinstance(raw, dict), f"{item_label} must be a mapping")
        _check_keys(raw, _REGISTRATION_KEYS[agent], item_label, required=False)
        event = raw.get("event")
        _require(isinstance(event, str) and bool(event), f"{item_label}.event is required")
        if "matcher" in raw:
            matcher = raw["matcher"]
            _require(
                isinstance(matcher, str) and bool(matcher),
                f"{item_label}.matcher must be a non-empty string",
            )
        registrations.append(dict(raw))
    return tuple(registrations)


def _parse_agent(agent: str, raw: object, base: PurePosixPath, label: str) -> HookAgent:
    _require(isinstance(raw, dict), f"{label} must be a mapping")
    _check_keys(raw, _AGENT_KEYS, label)
    runner = raw["runner"]
    _require(runner in RUNNERS, f"{label}.runner must be one of {', '.join(RUNNERS)}")
    files = _files(raw["files"], base, f"{label}.files")
    _require(bool(files), f"{label}.files must not be empty")
    main = _safe_path(raw["main"], f"{label}.main")
    _require(
        main in {item.install_path for item in files},
        f"{label}.main must be one of its files' installPath",
    )
    seed_files = _files(raw["seedFiles"], base, f"{label}.seedFiles")
    overlap = {item.install_path for item in files} & {item.install_path for item in seed_files}
    _require(not overlap, f"{label}: seedFiles collide with files at {sorted(map(str, overlap))}")
    dependencies = _string_list(raw["dependencies"], f"{label}.dependencies")
    _require(
        not dependencies or runner == "uv-script",
        f"{label}.dependencies are only valid with runner uv-script",
    )
    return HookAgent(
        agent=agent,
        runner=runner,
        main=main,
        files=files,
        seed_files=seed_files,
        dependencies=dependencies,
        registrations=_registrations(raw["registrations"], agent, f"{label}.registrations"),
    )


def _parse_hook(raw: object, base: PurePosixPath, label: str) -> HookRecord:
    _require(isinstance(raw, dict), f"{label} must be a mapping")
    _check_keys(raw, _HOOK_KEYS, label)
    hook_id = raw["id"]
    _require(
        isinstance(hook_id, str) and _HOOK_ID.fullmatch(hook_id) is not None,
        f"{label}.id must be a lowercase snake_case identifier",
    )
    label = f"hooks.{hook_id}"
    description = raw["description"]
    _require(
        isinstance(description, str) and bool(description.strip()),
        f"{label}.description must be a non-empty string",
    )
    _require(isinstance(raw["distributable"], bool), f"{label}.distributable must be a boolean")
    agents_raw = raw["agents"]
    _require(isinstance(agents_raw, dict) and bool(agents_raw), f"{label}.agents must be a mapping")
    unknown = set(agents_raw) - set(AGENTS)
    _require(not unknown, f"{label}.agents contains unknown agents: {', '.join(sorted(unknown))}")
    return HookRecord(
        id=hook_id,
        description=description.strip(),
        distributable=raw["distributable"],
        requires_tools=_string_list(raw["requiresTools"], f"{label}.requiresTools"),
        agents=tuple(
            _parse_agent(agent, agents_raw[agent], base, f"{label}.agents.{agent}")
            for agent in AGENTS
            if agent in agents_raw
        ),
    )


def parse_hook_catalog(data: Any, catalog_path: PurePosixPath) -> tuple[HookRecord, ...]:
    """Validate a parsed catalog.json. File paths resolve against its directory."""

    label = catalog_path.as_posix()
    _require(isinstance(data, dict), f"{label} must be a JSON object")
    _check_keys(data, {"schemaVersion", "generatedBy", "hooks"}, label)
    version = data["schemaVersion"]
    _require(
        type(version) is int and version == CATALOG_SCHEMA_VERSION,
        f"{label}: unsupported schemaVersion {version!r} (expected {CATALOG_SCHEMA_VERSION})",
    )
    _require(isinstance(data["hooks"], list), f"{label}.hooks must be a list")
    base = catalog_path.parent
    hooks = tuple(
        _parse_hook(raw, base, f"hooks[{index}]") for index, raw in enumerate(data["hooks"])
    )
    ids = [hook.id for hook in hooks]
    duplicates = sorted({hook_id for hook_id in ids if ids.count(hook_id) > 1})
    _require(not duplicates, f"{label} has duplicate hook ids: {', '.join(duplicates)}")
    return hooks


def _read_catalog_location(source: CatalogSource) -> PurePosixPath | None:
    # Probe first so "no repo-hooks.yaml" (no hooks) differs from "cannot read it".
    if not source.list_files((_REPO_HOOKS_PATH,)):
        return None
    try:
        data = yaml.safe_load(source.read_file(_REPO_HOOKS_PATH))
    except yaml.YAMLError as exc:
        raise CatalogError(f"{REPO_HOOKS_FILENAME} is invalid YAML: {exc}") from exc
    except SourceError as exc:
        raise CatalogError(f"could not read {REPO_HOOKS_FILENAME}: {exc}") from exc
    _require(isinstance(data, dict), f"{REPO_HOOKS_FILENAME} must be a mapping")
    _check_keys(data, {"version", "catalog"}, REPO_HOOKS_FILENAME)
    _require(
        type(data["version"]) is int and data["version"] == 1,
        f"{REPO_HOOKS_FILENAME}.version must be 1",
    )
    return _safe_path(data["catalog"], f"{REPO_HOOKS_FILENAME}.catalog")


def load_hook_catalog(source: CatalogSource) -> tuple[HookRecord, ...]:
    """Load every hook the source publishes; a source without repo-hooks.yaml has none."""

    catalog_path = _read_catalog_location(source)
    if catalog_path is None:
        return ()
    label = catalog_path.as_posix()
    try:
        raw = source.read_file(catalog_path)
    except SourceError as exc:
        raise CatalogError(
            f"{REPO_HOOKS_FILENAME}.catalog points to an unreadable file: {exc}"
        ) from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    hooks = parse_hook_catalog(data, catalog_path)
    present = set(source.list_files((catalog_path.parent,)))
    for hook in hooks:
        for path in hook.files:
            _require(path in present, f"hooks.{hook.id} references a missing file: {path}")
    return hooks


def filter_hooks(
    hooks: Iterable[HookRecord], *, agent: str | None = None, include_private: bool = False
) -> tuple[HookRecord, ...]:
    """Keep hooks for ``agent`` (any agent when None); drop non-distributable unless asked."""

    if agent is not None and agent not in AGENTS:
        raise CatalogError(f"unknown agent {agent!r}; expected one of {', '.join(AGENTS)}")
    return tuple(
        hook
        for hook in hooks
        if (include_private or hook.distributable)
        and (agent is None or hook.agent(agent) is not None)
    )


def hook_payload(hook: HookRecord, agents: Sequence[str] | None = None) -> dict[str, Any]:
    """Serialize a hook for ``--json``; paths are source-relative POSIX strings."""

    def files(items: Sequence[HookFile]) -> list[dict[str, str]]:
        return [
            {"path": item.source_path.as_posix(), "installPath": item.install_path.as_posix()}
            for item in items
        ]

    return {
        "id": hook.id,
        "description": hook.description,
        "distributable": hook.distributable,
        "requiresTools": list(hook.requires_tools),
        "agents": {
            item.agent: {
                "runner": item.runner,
                "main": item.main.as_posix(),
                "files": files(item.files),
                "seedFiles": files(item.seed_files),
                "dependencies": list(item.dependencies),
                "registrations": [dict(r) for r in item.registrations],
            }
            for item in hook.agents
            if agents is None or item.agent in agents
        },
    }
