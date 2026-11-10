"""Build a source-neutral skill catalog from the ai-tools.yaml SSOT."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from ..install.policy import load_bundle_policy
from ..models import CatalogError, SkillBundle, SkillRecord, SourceError
from ..registry import registry_file
from ..source import CatalogSource, LocalSource, display_skill_path

_VALID_LAYOUTS = {"subdir", "direct"}
_KNOWN_STATUSES = {"draft", "experimental", "stable", "deprecated"}
_FRONTMATTER = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
_TOOL_DISPLAY_NAMES = {
    "claude-code": "Claude Code",
    "cline": "Cline",
    "codex": "Codex",
    "copilot": "GitHub Copilot",
    "cursor": "Cursor",
    "antigravity": "Antigravity",
}
_ID_PREFIXES = {
    "claude-code": "claude",
    "cline": "cline",
    "codex": "codex",
    "copilot": "copilot",
    "cursor": "cursor",
    "antigravity": "antigravity",
}


@dataclass(frozen=True)
class _RegistryEntry:
    source_id: str
    tool: str
    plugin: str
    root: PurePosixPath


def _safe_relative_path(value: object, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise CatalogError(f"{label} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise CatalogError(f"{label} is unsafe: {value!r}")
    if "\\" in value or ":" in value:
        raise CatalogError(f"{label} is unsafe: {value!r}")
    return path


def _plugin_name(path: PurePosixPath, kind: object) -> str:
    base = path.name
    if kind == "workspace":
        return "workspace"
    return "meta" if base.startswith(".") else base


def _registry_id(prefix: str, path: PurePosixPath, plugin: str) -> str:
    if path.as_posix().startswith("."):
        return f"{prefix}-workspace"
    return plugin if plugin.startswith(f"{prefix}-") else f"{prefix}-{plugin}"


def _load_yaml(source: CatalogSource, path: PurePosixPath, label: str) -> Any:
    try:
        return yaml.safe_load(source.read_file(path))
    except yaml.YAMLError as exc:
        raise CatalogError(f"{label} is invalid YAML: {exc}") from exc


def _registry(source: CatalogSource) -> tuple[_RegistryEntry, ...]:
    config = _load_yaml(source, registry_file(source, "ai-tools.yaml"), "ai-tools.yaml")
    if not isinstance(config, dict) or not isinstance(config.get("tools"), dict):
        raise CatalogError("ai-tools.yaml must contain a tools mapping")

    entries: list[_RegistryEntry] = []
    roots: set[PurePosixPath] = set()
    for tool_key, tool in config["tools"].items():
        if not isinstance(tool_key, str) or not isinstance(tool, dict):
            raise CatalogError("each tools entry in ai-tools.yaml must be a mapping")
        prefix = _ID_PREFIXES.get(tool_key, tool_key)
        display_name = _TOOL_DISPLAY_NAMES.get(tool_key, tool_key)
        plugins = tool.get("plugins")
        if not isinstance(plugins, list):
            raise CatalogError(f"tools.{tool_key}.plugins must be a list")
        for index, plugin in enumerate(plugins):
            if not isinstance(plugin, dict):
                raise CatalogError(f"tools.{tool_key}.plugins[{index}] must be a mapping")
            path = _safe_relative_path(
                plugin.get("path"), f"tools.{tool_key}.plugins[{index}].path"
            )
            layout = plugin.get("skills_layout")
            if layout not in _VALID_LAYOUTS:
                raise CatalogError(
                    f"tools.{tool_key}.plugins[{index}].skills_layout must be one of "
                    f"{', '.join(sorted(_VALID_LAYOUTS))}"
                )
            root = path / "skills" if layout == "subdir" else path
            if root in roots:
                raise CatalogError(f"skill root is registered more than once: {root}")
            roots.add(root)
            plugin_name = _plugin_name(path, plugin.get("kind"))
            entries.append(
                _RegistryEntry(
                    source_id=_registry_id(prefix, path, plugin_name),
                    tool=display_name,
                    plugin=plugin_name,
                    root=root,
                )
            )
    return tuple(entries)


def _site_overrides(source: CatalogSource) -> tuple[set[str], set[str]]:
    try:
        data = _load_yaml(
            source, PurePosixPath("site/skills-site/site-overrides.yaml"), "site-overrides.yaml"
        )
    except SourceError:
        return set(), set()
    if data is None:
        return set(), set()
    if not isinstance(data, dict):
        raise CatalogError("site-overrides.yaml must contain a mapping")
    exclude = data.get("exclude", {})
    if not isinstance(exclude, dict):
        raise CatalogError("site-overrides.yaml.exclude must contain a mapping")
    source_ids = exclude.get("sources", [])
    skill_paths = exclude.get("skills", [])
    if not isinstance(source_ids, list) or not all(isinstance(value, str) for value in source_ids):
        raise CatalogError("site-overrides.yaml.exclude.sources must be a list of strings")
    if not isinstance(skill_paths, list) or not all(
        isinstance(value, str) for value in skill_paths
    ):
        raise CatalogError("site-overrides.yaml.exclude.skills must be a list of strings")
    return set(source_ids), set(skill_paths)


def _parse_skill_document(content: bytes, display_path: str) -> tuple[str, str, str, str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CatalogError(f"{display_path}: SKILL.md is not UTF-8") from exc
    match = _FRONTMATTER.match(text)
    if not match:
        raise CatalogError(f"{display_path}: YAML frontmatter is missing or incomplete")
    try:
        data = yaml.safe_load(match.group("body"))
    except yaml.YAMLError as exc:
        raise CatalogError(f"{display_path}: invalid YAML frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise CatalogError(f"{display_path}: frontmatter must be a YAML mapping")
    name = data.get("name")
    description = data.get("description")
    if not isinstance(name, str) or not name.strip():
        raise CatalogError(f"{display_path}: frontmatter field 'name' must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise CatalogError(
            f"{display_path}: frontmatter field 'description' must be a non-empty string"
        )
    meta = data.get("meta")
    if meta is None:
        status = "unset"
    elif isinstance(meta, dict):
        raw_status = meta.get("status")
        status = (
            "unset"
            if raw_status is None or not str(raw_status).strip()
            else str(raw_status).strip()
        )
        status = status.lower() if status.lower() in _KNOWN_STATUSES else "unknown"
    else:
        raise CatalogError(f"{display_path}: frontmatter field 'meta' must be a mapping")
    return name.strip(), description.strip(), status, text[match.end() :]


def discover_catalog(source: CatalogSource) -> tuple[SkillRecord, ...]:
    """Discover registered skills and their deployable bundle files."""

    registry = _registry(source)
    excluded_sources, excluded_skills = _site_overrides(source)
    active = tuple(entry for entry in registry if entry.source_id not in excluded_sources)
    roots = tuple(entry.root for entry in active)
    policy = load_bundle_policy(source)
    files = tuple(sorted(source.list_files(roots)))
    skill_entries: dict[PurePosixPath, _RegistryEntry] = {}
    for entry in active:
        for path in files:
            if path.name == "SKILL.md" and path.is_relative_to(entry.root):
                if path.as_posix() in excluded_skills:
                    continue
                if path in skill_entries:
                    raise CatalogError(f"skill is registered more than once: {path}")
                skill_entries[path] = entry

    skill_dirs = set(path.parent for path in skill_entries)
    files_by_skill: dict[PurePosixPath, list[PurePosixPath]] = {
        directory: [] for directory in skill_dirs
    }
    bundled: dict[PurePosixPath, set[PurePosixPath]] = {
        directory: set() for directory in skill_dirs
    }
    for path in files:
        owner = next((ancestor for ancestor in path.parents if ancestor in skill_dirs), None)
        if owner is None:
            continue
        relative = path.relative_to(owner)
        if not policy.keep(relative):
            continue
        files_by_skill[owner].append(relative)
        bundled[owner].add(relative)

    if isinstance(source, LocalSource) and policy.include_lines:
        # Git hides ignored files from ``list_files``; an explicit include can
        # still restore them (``.env`` etc.) from the local checkout. With no
        # includes there is nothing to rescue, so the walk is skipped entirely.
        for skill_dir in skill_dirs:
            for relative in source.include_candidates(skill_dir, policy):
                if relative in bundled[skill_dir]:
                    continue
                files_by_skill[skill_dir].append(relative)
                bundled[skill_dir].add(relative)

    records: list[SkillRecord] = []
    for skill_path in sorted(skill_entries):
        skill_dir = skill_path.parent
        bundled_files = tuple(sorted(files_by_skill[skill_dir]))
        if PurePosixPath("SKILL.md") not in bundled_files:
            raise CatalogError(f"{skill_path} did not include its SKILL.md")
        name, description, status, body = _parse_skill_document(
            source.read_file(skill_path), skill_path.as_posix()
        )
        bundle = SkillBundle(
            canonical_id=skill_path.as_posix(),
            name=skill_dir.name,
            directory=skill_dir,
            files=bundled_files,
        )
        entry = skill_entries[skill_path]
        records.append(
            SkillRecord(
                bundle=bundle,
                name=name,
                description=description,
                body=body,
                status=status,
                tool=entry.tool,
                plugin=entry.plugin,
            )
        )
    return tuple(records)


def discover_bundles(source: CatalogSource) -> tuple[SkillBundle, ...]:
    """Compatibility view containing only install bundle data."""

    return tuple(record.bundle for record in discover_catalog(source))


def _record_by_display_path(
    records: Iterable[SkillRecord], selector: str, descriptor: Mapping[str, str]
) -> SkillRecord | None:
    displayed = {display_skill_path(record.canonical_id, descriptor): record for record in records}
    record = displayed.get(selector)
    if record is not None:
        return record
    if descriptor.get("type") != "local":
        return None
    try:
        normalized = str(Path(selector).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return displayed.get(normalized)


def select_records(
    records: Iterable[SkillRecord],
    selectors: Iterable[str],
    *,
    source_descriptor: Mapping[str, str] | None = None,
) -> tuple[SkillRecord, ...]:
    """Resolve canonical IDs, display paths, or a unique frontmatter / directory skill name."""

    catalog = tuple(records)
    records_by_id = {record.canonical_id: record for record in catalog}
    selected: list[SkillRecord] = []
    for selector in selectors:
        record = records_by_id.get(selector)
        if record is None and source_descriptor is not None:
            record = _record_by_display_path(catalog, selector, source_descriptor)
        if record is None:
            matches = [item for item in records_by_id.values() if item.name == selector]
            if not matches:
                matches = [item for item in records_by_id.values() if item.bundle.name == selector]
            if not matches:
                raise CatalogError(f"skill not found: {selector}")
            if len(matches) > 1:
                options = ", ".join(
                    sorted(
                        display_skill_path(item.canonical_id, source_descriptor) for item in matches
                    )
                )
                raise CatalogError(
                    f"skill name {selector!r} is ambiguous; use one of these paths: {options}"
                )
            record = matches[0]
        if record not in selected:
            selected.append(record)
    return tuple(selected)
