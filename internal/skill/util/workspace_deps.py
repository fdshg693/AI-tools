"""Read [project].name and uv workspace deps from a tool's pyproject.toml.

Used by the requires_tools checker and (later) the skill/tool impact query so
TOML is parsed in one place. Package names come from each registered tool's
pyproject; repo-tools.yaml keys are never hardcoded.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

_VERSION_SPECIFIERS = ("===", "==", "!=", "~=", ">=", "<=", ">", "<")


def load_pyproject(path: Path) -> dict[str, Any] | None:
    """Return parsed TOML, or None if the file is absent."""
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return data if isinstance(data, dict) else None


def project_name(data: dict[str, Any]) -> str | None:
    name = data.get("project", {}).get("name") if isinstance(data.get("project"), dict) else None
    return name if isinstance(name, str) and name.strip() else None


def requirement_name(raw: str) -> str:
    """PEP 508 requirement string -> distribution name (no extras/markers/spec)."""
    name = raw.split(";", 1)[0].strip()
    name = name.split("[", 1)[0].strip()
    for spec in _VERSION_SPECIFIERS:
        idx = name.find(spec)
        if idx != -1:
            name = name[:idx].strip()
            break
    return name


def normalize_package_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def workspace_dependency_names(data: dict[str, Any]) -> set[str]:
    """Workspace packages that are also listed in [project].dependencies."""
    sources = (
        data.get("tool", {}).get("uv", {}).get("sources", {})
        if isinstance(data.get("tool"), dict)
        else {}
    )
    if not isinstance(sources, dict):
        return set()
    workspace_names = {
        normalize_package_name(name)
        for name, spec in sources.items()
        if isinstance(name, str) and isinstance(spec, dict) and spec.get("workspace") is True
    }
    raw_deps = (
        data.get("project", {}).get("dependencies", [])
        if isinstance(data.get("project"), dict)
        else []
    )
    if not isinstance(raw_deps, list):
        return set()
    dep_names = {
        normalize_package_name(requirement_name(item))
        for item in raw_deps
        if isinstance(item, str) and requirement_name(item)
    }
    return workspace_names & dep_names


def tool_keys_by_project_name(
    tools: dict[str, dict[str, Any]],
    repo_root: Path,
) -> dict[str, str]:
    """Map normalized [project].name -> repo-tools.yaml key for tools with pyproject.toml."""
    mapping: dict[str, str] = {}
    for key, entry in tools.items():
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(path, str):
            continue
        data = load_pyproject(repo_root / path / "pyproject.toml")
        if data is None:
            continue
        name = project_name(data)
        if name is None:
            continue
        mapping[normalize_package_name(name)] = key
    return mapping
