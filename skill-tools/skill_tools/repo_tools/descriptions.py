"""Resolve the summary text a repo tool's ``description`` locator points at.

``repo-tools.yaml`` records only *where* each tool's summary lives (a
repo-relative path plus an optional dotted key). This module performs the read
that turns such a locator into the one-line summary ``list-tools`` prints.

The format is chosen by extension: ``.toml`` / ``.json`` / ``.yaml`` / ``.yml``
require a ``#key`` and are parsed then walked, while every other extension is
treated as plain text whose first heading (or first non-empty line) is the
summary. A broken locator raises :class:`CatalogError` rather than silently
degrading to an empty summary.
"""

from __future__ import annotations

import json
import tomllib
from typing import Any

import yaml

from ..models import CatalogError, SourceError
from ..source import CatalogSource
from .load import DescriptionLocator, RepoTool

_STRUCTURED_SUFFIXES = frozenset({".toml", ".json", ".yaml", ".yml"})
_FRONTMATTER_FENCES = frozenset({"---", "..."})
_HEADING_PREFIXES = "#>"


def _field(tool: RepoTool) -> str:
    return f"tools.{tool.key}.description"


def _parse_structured(text: str, suffix: str, locator: DescriptionLocator, field: str) -> Any:
    try:
        if suffix == ".toml":
            return tomllib.loads(text)
        if suffix == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (tomllib.TOMLDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise CatalogError(f"{field} could not parse {locator.as_text()}: {exc}") from exc


def _lookup(data: Any, key: str, locator: DescriptionLocator, field: str) -> Any:
    current = data
    for part in key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise CatalogError(f"{field} key {key!r} was not found in {locator.as_text()}")
    return current


def _frontmatter_end(lines: list[str]) -> int:
    """Return the first content line, skipping a leading YAML frontmatter block."""

    if not lines or lines[0].strip() != "---":
        return 0
    for index in range(1, len(lines)):
        if lines[index].strip() in _FRONTMATTER_FENCES:
            return index + 1
    return 0


def _plain_text_summary(text: str, locator: DescriptionLocator, field: str) -> str:
    if locator.key is not None:
        raise CatalogError(
            f"{field} must not include a #key for a plain-text file: {locator.as_text()}"
        )

    lines = text.splitlines()
    heading: str | None = None
    first_line: str | None = None
    for line in lines[_frontmatter_end(lines) :]:
        stripped = line.strip()
        if not stripped:
            continue
        if first_line is None:
            first_line = stripped
        if stripped[0] in _HEADING_PREFIXES:
            heading = stripped.lstrip("#> ").strip()
            break

    summary = heading or first_line
    if not summary:
        raise CatalogError(f"{field} has no summary line: {locator.as_text()}")
    return summary


def _read_text(source: CatalogSource, locator: DescriptionLocator, field: str) -> str:
    try:
        raw = source.read_file(locator.path)
    except SourceError as exc:
        raise CatalogError(f"{field} could not be read ({locator.as_text()}): {exc}") from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CatalogError(f"{field} is not valid UTF-8 ({locator.as_text()}): {exc}") from exc


def resolve_description(tool: RepoTool, source: CatalogSource) -> str:
    """Return the resolved one-line summary, or ``""`` when no locator is set."""

    locator = tool.description
    if locator is None:
        return ""

    field = _field(tool)
    text = _read_text(source, locator, field)
    suffix = locator.path.suffix.lower()
    if suffix not in _STRUCTURED_SUFFIXES:
        return _plain_text_summary(text, locator, field)

    if locator.key is None:
        raise CatalogError(f"{field} must include a #key for a {suffix} file: {locator.as_text()}")
    data = _parse_structured(text, suffix, locator, field)
    value = _lookup(data, locator.key, locator, field)
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(
            f"{field} key {locator.key!r} must resolve to a non-empty string: {locator.as_text()}"
        )
    return value.strip()
