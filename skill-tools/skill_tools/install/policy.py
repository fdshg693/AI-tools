"""Exclude/include policy for the files copied into a skill bundle.

The policy is a pure-logic layer: it turns ``tools/skill-tools/.gitignore``
(excludes) and ``tools/skill-tools/.skill-tools`` (includes) into a single
decision for a bundle-relative path. It never touches the filesystem itself;
callers pass a ``CatalogSource`` so local and GitHub sources share one path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import yaml
from pathspec import GitIgnoreSpec

from ..models import CatalogError

if TYPE_CHECKING:
    from ..source import CatalogSource

# Policy files are read from the source root so the same SSOT works for local
# clones and GitHub trees, and so a source without them falls back to defaults.
GITIGNORE_PATH = PurePosixPath("tools/skill-tools/.gitignore")
INCLUDE_PATH = PurePosixPath("tools/skill-tools/.skill-tools")

# Dependency and cache directories pruned from untracked walks and excluded
# from bundles by default. ``_UNTRACKED_WALK_EXCLUDES`` in ``source`` reuses it.
DEFAULT_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".codegraph",
        ".pnpm-store",
        ".turbo",
        ".next",
        ".astro",
    }
)

# Built-in bundle excludes: dependency/cache directories plus the ``.env``
# safety net, applied when the source provides no policy files.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    *(f"{name}/" for name in sorted(DEFAULT_EXCLUDED_DIRECTORIES)),
    ".env",
)

# Sentinel for the case-insensitive ``.env`` comparison: gitignore matching is
# case-sensitive, but secret files must be excluded regardless of case.
_ENV_BASENAME = ".env"


def _is_env_path(path: PurePosixPath) -> bool:
    return path.name.lower() == _ENV_BASENAME


def _lowered(path: PurePosixPath) -> PurePosixPath:
    return PurePosixPath(*(part.lower() for part in path.parts))


def _validate_pattern(pattern: str, label: str) -> None:
    raw = pattern[1:] if pattern.startswith("!") else pattern
    if not raw:
        raise CatalogError(f"{label} contains an empty pattern")
    candidate = PurePosixPath(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise CatalogError(f"{label} pattern is unsafe: {pattern!r}")


def _read_optional_text(source: CatalogSource, path: PurePosixPath) -> str | None:
    """Return the text of ``path`` through ``source``, or None when absent.

    Existence is probed with ``list_files`` so a missing policy file falls back
    to the built-in defaults, while a file that exists but cannot be read keeps
    raising instead of silently ignoring the SSOT.
    """

    if not source.list_files((path,)):
        return None
    try:
        return source.read_file(path).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CatalogError(f"{path.as_posix()} is not UTF-8: {exc}") from exc


def _load_exclude_lines(source: CatalogSource) -> tuple[str, ...]:
    text = _read_optional_text(source, GITIGNORE_PATH)
    if text is None:
        return ()
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        _validate_pattern(line, GITIGNORE_PATH.as_posix())
        lines.append(line)
    return tuple(lines)


def _load_include_lines(source: CatalogSource) -> tuple[str, ...]:
    text = _read_optional_text(source, INCLUDE_PATH)
    if text is None:
        return ()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CatalogError(f"{INCLUDE_PATH.as_posix()} is invalid YAML: {exc}") from exc
    if data is None:
        return ()
    if not isinstance(data, dict):
        raise CatalogError(f"{INCLUDE_PATH.as_posix()} must contain a mapping")
    unknown = sorted(set(data) - {"include"})
    if unknown:
        raise CatalogError(f"{INCLUDE_PATH.as_posix()} has unknown keys: {', '.join(unknown)}")
    include = data.get("include", [])
    if not isinstance(include, list) or not all(isinstance(value, str) for value in include):
        raise CatalogError(f"{INCLUDE_PATH.as_posix()}.include must be a list of strings")
    for pattern in include:
        _validate_pattern(pattern, f"{INCLUDE_PATH.as_posix()}.include")
    return tuple(include)


@dataclass(frozen=True)
class BundlePolicy:
    """Decide whether a bundle-relative path is copied into an install.

    Precedence is one-directional: built-in defaults, then ``.gitignore``
    (including ``!`` negations), then the ``.skill-tools`` include list as the
    final override. ``.env`` matches case-insensitively (``.ENV`` / ``.Env``).
    """

    exclude_lines: tuple[str, ...] = ()
    include_lines: tuple[str, ...] = ()
    _exclude: GitIgnoreSpec = field(init=False, repr=False, compare=False)
    _include: GitIgnoreSpec = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_exclude",
            GitIgnoreSpec.from_lines([*DEFAULT_EXCLUDES, *self.exclude_lines]),
        )
        object.__setattr__(self, "_include", GitIgnoreSpec.from_lines(self.include_lines))

    def included(self, relative_path: PurePosixPath | str) -> bool:
        """Return True when the ``.skill-tools`` include list restores the path.

        Used by the local include rescue to tell "explicitly included" apart from
        "merely not excluded", so untracked files are not swept in by accident.
        """

        path = PurePosixPath(relative_path)
        if self._include.match_file(path):
            return True
        return _is_env_path(path) and self._include.match_file(_lowered(path))

    def keep(self, relative_path: PurePosixPath | str) -> bool:
        path = PurePosixPath(relative_path)
        if self.included(path):
            return True
        if _is_env_path(path):
            return not self._exclude.match_file(_lowered(path))
        return not self._exclude.match_file(path)


def load_bundle_policy(source: CatalogSource) -> BundlePolicy:
    """Read the bundle policy files through ``source``.

    A missing policy file falls back to the built-in defaults; a file that
    exists but cannot be read or parsed raises instead of silently skipping it.
    """

    return BundlePolicy(
        exclude_lines=_load_exclude_lines(source),
        include_lines=_load_include_lines(source),
    )
