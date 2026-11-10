"""Enumerate and install the first-class CLI tools registered in repo-tools.yaml.

``repo-tools.yaml`` is the repository SSOT for ``tools/``-rooted CLI tools. This
module reads it through the configured ``CatalogSource`` (so the same local or
GitHub source that provides skills also provides the tool registry) and runs the
per-tool ``install`` command. The ``release`` field is intentionally ignored:
tag+GitHub Release targeting is a separate concern, and every registered tool is
an enumeration / installation target here.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from ..models import CatalogError, InstallError, SourceError
from ..source import CatalogSource, LocalSource

REPO_TOOLS_FILENAME = "repo-tools.yaml"
_REPO_TOOLS_PATH = PurePosixPath(REPO_TOOLS_FILENAME)
# requires_tools is accepted but ignored: intra-repo tool dependencies are
# already expressed by each package's pyproject.toml / workspace deps, so
# installing a tool never implies installing or ordering its dependencies.
_KNOWN_ENTRY_KEYS = {"path", "install", "release", "requires_tools", "description"}


@dataclass(frozen=True)
class DescriptionLocator:
    """Where a tool's summary lives: a repo-relative path and an optional dotted key.

    ``key`` is required for the structured formats (TOML / JSON / YAML) and is
    rejected for plain-text files, but that split is enforced by the resolver in
    :mod:`skill_tools.repo_tools.descriptions`, not here.
    """

    path: PurePosixPath
    key: str | None = None

    def as_text(self) -> str:
        text = self.path.as_posix()
        return text if self.key is None else f"{text}#{self.key}"


@dataclass(frozen=True)
class RepoTool:
    """One ``tools/``-rooted CLI registered in repo-tools.yaml."""

    key: str
    path: PurePosixPath
    install: str
    release: bool = False
    description: DescriptionLocator | None = None


def _safe_relative_path(value: object, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise CatalogError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise CatalogError(f"{field} is unsafe: {value!r}")
    if "\\" in value or ":" in value:
        raise CatalogError(f"{field} is unsafe: {value!r}")
    return path


def _safe_tool_path(value: object, key: str) -> PurePosixPath:
    return _safe_relative_path(value, f"tools.{key}.path")


def parse_locator(value: object, key: str) -> DescriptionLocator:
    """Validate a ``<repo-relative path>[#<dotted key>]`` description locator."""

    field = f"tools.{key}.description"
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{field} must be a non-empty locator string")
    path_text, separator, locator_key = value.strip().partition("#")
    if not path_text:
        raise CatalogError(f"{field} is missing a path: {value!r}")
    path = _safe_relative_path(path_text, field)
    if not separator:
        return DescriptionLocator(path=path)
    locator_key = locator_key.strip()
    if not locator_key:
        raise CatalogError(f"{field} has an empty key: {value!r}")
    return DescriptionLocator(path=path, key=locator_key)


def parse_repo_tools(data: Any) -> tuple[RepoTool, ...]:
    """Validate a parsed repo-tools.yaml document into tool entries."""

    if not isinstance(data, dict) or not isinstance(data.get("tools"), dict):
        raise CatalogError(f"{REPO_TOOLS_FILENAME} must contain a tools mapping")

    tools: list[RepoTool] = []
    for key, entry in data["tools"].items():
        if not isinstance(key, str) or not key:
            raise CatalogError(f"each tools entry in {REPO_TOOLS_FILENAME} must have a name")
        if not isinstance(entry, dict):
            raise CatalogError(f"tools.{key} must be a mapping")
        unknown = set(entry) - _KNOWN_ENTRY_KEYS
        if unknown:
            raise CatalogError(f"tools.{key} contains unknown keys: {', '.join(sorted(unknown))}")
        path = _safe_tool_path(entry.get("path"), key)
        install = entry.get("install")
        if not isinstance(install, str) or not install.strip():
            raise CatalogError(f"tools.{key}.install must be a non-empty command string")
        release = entry.get("release", False)
        if not isinstance(release, bool):
            raise CatalogError(f"tools.{key}.release must be a boolean")
        description = None
        if "description" in entry:
            description = parse_locator(entry["description"], key)
        tools.append(
            RepoTool(
                key=key,
                path=path,
                install=install.strip(),
                release=release,
                description=description,
            )
        )
    return tuple(tools)


def load_repo_tools(source: CatalogSource) -> tuple[RepoTool, ...]:
    """Read and validate repo-tools.yaml, checking that each registered path exists."""

    try:
        raw = source.read_file(_REPO_TOOLS_PATH)
    except SourceError as exc:
        raise CatalogError(f"could not read {REPO_TOOLS_FILENAME}: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise CatalogError(f"{REPO_TOOLS_FILENAME} is invalid YAML: {exc}") from exc

    tools = parse_repo_tools(data)
    for tool in tools:
        if not source.list_files((tool.path,)):
            raise CatalogError(
                f"tools.{tool.key}.path does not exist in the source: {tool.path.as_posix()}"
            )
        if tool.description is not None and not source.list_files((tool.description.path,)):
            raise CatalogError(
                f"tools.{tool.key}.description does not exist in the source: "
                f"{tool.description.path.as_posix()}"
            )
    return tools


def select_repo_tools(tools: Iterable[RepoTool], selectors: Sequence[str]) -> tuple[RepoTool, ...]:
    """Resolve tool names or repo-relative paths; an empty selector list means all."""

    catalog = tuple(tools)
    if not selectors:
        return catalog
    by_key = {tool.key: tool for tool in catalog}
    by_path = {tool.path.as_posix(): tool for tool in catalog}
    selected: list[RepoTool] = []
    for selector in selectors:
        tool = by_key.get(selector) or by_path.get(selector)
        if tool is None:
            raise CatalogError(f"repo tool not found: {selector}")
        if tool not in selected:
            selected.append(tool)
    return tuple(selected)


def resolve_install_root(source: CatalogSource) -> Path:
    """Return the directory the install commands run from.

    The commands in repo-tools.yaml use repository-relative paths (for example
    ``uv tool install --editable tools/aim``), so installation needs a local
    clone. A GitHub source has no working tree to run them in.
    """

    if not isinstance(source, LocalSource):
        raise InstallError(
            "installing repo tools requires a local source; "
            "clone the repository and set source.type: local"
        )
    return source.root


def install_repo_tools(
    tools: Sequence[RepoTool],
    root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> tuple[RepoTool, ...]:
    """Run each tool's install command in ``root``, stopping at the first failure."""

    run = runner or subprocess.run
    installed: list[RepoTool] = []
    for tool in tools:
        try:
            completed = run(tool.install, cwd=root, shell=True, check=False)
        except OSError as exc:
            raise InstallError(f"could not run install for {tool.key}: {exc}") from exc
        if completed.returncode != 0:
            raise InstallError(
                f"install failed for {tool.key} (exit {completed.returncode}): {tool.install}"
            )
        installed.append(tool)
    return tuple(installed)
