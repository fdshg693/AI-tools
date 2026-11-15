"""The repository's ``.textgraph.toml``: which files textgraph leaves out.

Only the file at the repository root is read. The index covers one
repository root, so ``sync`` and ``check`` must always see the same
exclusions; a CWD walk or a global file would let them drift apart.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = ".textgraph.toml"
KNOWN_KEYS = ("exclude", "scripts_exclude")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    """Exclusion globs from ``.textgraph.toml`` (empty when the file is absent).

    ``exclude`` removes paths from the index, the stale check and the
    ``--scripts`` scan. ``scripts_exclude`` only removes paths from the
    ``--scripts`` scan. Neither changes the file set links resolve against,
    so a link to an excluded file still resolves exactly.
    """

    path: Path | None = None
    exclude: tuple[str, ...] = ()
    scripts_exclude: tuple[str, ...] = ()
    _exclude_re: tuple[re.Pattern[str], ...] = field(default=(), repr=False, compare=False)
    _scripts_re: tuple[re.Pattern[str], ...] = field(default=(), repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_exclude_re", tuple(compile_glob(p) for p in self.exclude))
        object.__setattr__(
            self, "_scripts_re", tuple(compile_glob(p) for p in self.scripts_exclude)
        )

    def excludes(self, path: str) -> bool:
        return any(pattern.fullmatch(path) for pattern in self._exclude_re)

    def excludes_script(self, path: str) -> bool:
        return self.excludes(path) or any(pattern.fullmatch(path) for pattern in self._scripts_re)

    def sources(self, paths: Iterable[str]) -> list[str]:
        """Paths that are not excluded, in the given order."""
        if not self._exclude_re:
            return list(paths)
        return [path for path in paths if not self.excludes(path)]


def load_config(root: Path) -> Config:
    path = root / CONFIG_NAME
    if not path.is_file():
        return Config()
    shown = path.resolve()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{shown}: invalid TOML: {exc}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{shown}: cannot read: {exc}") from exc
    unknown = sorted(set(data) - set(KNOWN_KEYS))
    if unknown:
        raise ConfigError(
            f"{shown}: unknown key(s): {', '.join(unknown)} (known: {', '.join(KNOWN_KEYS)})"
        )
    return Config(
        path=shown,
        exclude=_glob_list(data, "exclude", shown),
        scripts_exclude=_glob_list(data, "scripts_exclude", shown),
    )


def _glob_list(data: dict[str, object], key: str, shown: Path) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ConfigError(f"{shown}: {key} must be an array of strings, got {type(value).__name__}")
    patterns: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ConfigError(
                f"{shown}: {key}[{index}] must be a string, got {type(item).__name__}"
            )
        if not _normalize(item):
            raise ConfigError(f"{shown}: {key}[{index}] is empty")
        patterns.append(item)
    return tuple(patterns)


def _normalize(pattern: str) -> str:
    text = pattern.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def compile_glob(pattern: str) -> re.Pattern[str]:
    """Compile a repository-relative glob to a full-match regex.

    ``*``, ``?`` and ``[...]`` stay within one path segment. A ``**``
    segment matches zero or more whole directories (``a/**/b`` matches
    ``a/b`` and ``a/x/y/b``); a trailing ``**`` matches everything below.
    A trailing ``/`` means the same as ``/**``. The pattern is matched
    against the whole path from the root (no gitignore-style floating
    match): write ``**/tests/**`` for any ``tests`` directory.
    """
    text = _normalize(pattern)
    if text.endswith("/"):
        text += "**"
    parts = text.split("/")
    out: list[str] = []
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == "**":
            out.append(".*" if last else "(?:[^/]+/)*")
        else:
            out.append(_segment(part) + ("" if last else "/"))
    return re.compile("".join(out))


def _segment(part: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(part):
        char = part[index]
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            end = part.find("]", index + 2)
            if end == -1:
                out.append(re.escape(char))
            else:
                body = part[index + 1 : end]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                index = end
        else:
            out.append(re.escape(char))
        index += 1
    return "".join(out)
