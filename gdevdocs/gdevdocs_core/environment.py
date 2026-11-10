"""Layered settings for the Developer Knowledge CLI.

Resolution (highest precedence first; see ``docs/repo-wide/tool-conventions.md``):

1. Process environment variables, even when set to empty.
2. Project config ``.gdevdocs.toml``, searched from the cwd up to the git root
   (inclusive; outside a git repo only the cwd). The nearest file wins per key.
3. Global config ``<config home>/config.toml`` (``$GDEVDOCS_CONFIG_HOME``, else
   ``$XDG_CONFIG_HOME/gdevdocs``, else ``~/.config/gdevdocs``).
4. Built-in defaults.

``api_key`` is accepted only from the environment or the global config — a
project file may be committed, so a key there is rejected with an error.
The repo-root ``.env`` is not read.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gdevdocs_core.config import (
    API_KEY_ENV,
    CONFIG_HOME_ENV,
    DEFAULT_ENDPOINT,
    DEFAULT_OUTPUT_DIR,
    ENDPOINT_ENV,
    OUTPUT_DIR_ENV,
)

PROJECT_CONFIG_NAME = ".gdevdocs.toml"
GLOBAL_CONFIG_NAME = "config.toml"
TOOL_CONFIG_DIR = "gdevdocs"

SETTINGS: dict[str, tuple[str, type]] = {
    "api_key": (API_KEY_ENV, str),
    "output_dir": (OUTPUT_DIR_ENV, str),
    "endpoint": (ENDPOINT_ENV, str),
}
GLOBAL_ONLY_SETTINGS = frozenset({"api_key"})


class ConfigError(ValueError):
    """A config file exists but cannot be used (bad TOML, unknown key, wrong type)."""


@dataclass(frozen=True)
class ConfigFile:
    path: Path
    scope: str  # "project" | "global"
    values: dict[str, Any]


@dataclass(frozen=True)
class ResolvedSetting:
    value: Any
    source: str
    base_dir: Path | None


def global_config_path() -> Path:
    override = os.getenv(CONFIG_HOME_ENV, "").strip()
    if override:
        return Path(override).expanduser() / GLOBAL_CONFIG_NAME
    xdg = os.getenv("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / TOOL_CONFIG_DIR / GLOBAL_CONFIG_NAME


def find_git_root(start: Path | None = None) -> Path | None:
    """Nearest ancestor (inclusive) holding ``.git`` — a dir, or a file for worktrees."""
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        if (directory / ".git").exists():
            return directory
    return None


def project_config_paths(cwd: Path | None = None) -> list[Path]:
    """Existing ``.gdevdocs.toml`` files from the cwd up to the git root, nearest first."""
    current = (cwd or Path.cwd()).resolve()
    git_root = find_git_root(current)
    directories = [current]
    if git_root is not None:
        directories = [current, *current.parents]
        directories = directories[: directories.index(git_root) + 1]
    return [d / PROJECT_CONFIG_NAME for d in directories if (d / PROJECT_CONFIG_NAME).is_file()]


def _read_config(path: Path, scope: str) -> ConfigFile:
    try:
        values = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"設定ファイル {path} を読めません: {exc}") from exc
    if not isinstance(values, dict):
        raise ConfigError(f"設定ファイル {path} のトップレベルはテーブルである必要があります")
    for key, value in values.items():
        if key not in SETTINGS:
            allowed = ", ".join(SETTINGS)
            raise ConfigError(f"設定ファイル {path} の未知のキー {key!r}（使えるキー: {allowed}）")
        if scope == "project" and key in GLOBAL_ONLY_SETTINGS:
            raise ConfigError(
                f"設定ファイル {path} に {key!r} は書けません（コミットされうるため）。"
                f"環境変数 {SETTINGS[key][0]} かグローバル設定 {global_config_path()} に置いてください。"
            )
        expected = SETTINGS[key][1]
        if not isinstance(value, expected):
            raise ConfigError(
                f"設定ファイル {path} の {key!r} は {expected.__name__} である必要があります"
                f"（実際: {type(value).__name__}）"
            )
    return ConfigFile(path=path.resolve(), scope=scope, values=values)


def load_config_files(cwd: Path | None = None) -> list[ConfigFile]:
    """All config files that exist, in precedence order (nearest project, then global)."""
    files = [_read_config(p, "project") for p in project_config_paths(cwd)]
    global_path = global_config_path()
    if global_path.is_file():
        files.append(_read_config(global_path, "global"))
    return files


def resolve_setting(key: str, cwd: Path | None = None) -> ResolvedSetting:
    env_name = SETTINGS[key][0]
    if env_name in os.environ:
        return ResolvedSetting(os.environ[env_name], f"env:{env_name}", None)
    for config in load_config_files(cwd):
        if key in config.values:
            base_dir = config.path.parent if config.scope == "project" else None
            return ResolvedSetting(config.values[key], str(config.path), base_dir)
    return ResolvedSetting(None, "default", None)


def get_normalized_api_key() -> str:
    value = resolve_setting("api_key").value
    return value.strip() if isinstance(value, str) else ""


def get_missing_api_key_message() -> str:
    """Every place looked at, and why each gave nothing."""
    env_state = "未設定" if API_KEY_ENV not in os.environ else "空で設定されている"
    global_path = global_config_path()
    if not global_path.is_file():
        file_state = f"グローバル設定 {global_path} がありません。"
    else:
        file_state = f"グローバル設定 {global_path} はありますが、api_key が無いか空です。"
    return (
        f"{API_KEY_ENV} が解決できません。\n"
        f"環境変数 {API_KEY_ENV} は{env_state}です。\n"
        f"{file_state}\n"
        f"(プロジェクト設定 {PROJECT_CONFIG_NAME} からは api_key を読みません)\n"
        "キーの設定と Developer Knowledge API（developerknowledge.googleapis.com）の"
        "有効化手順は README.md にあります。"
    )


def require_api_key() -> str:
    """Return the API key, or raise ``ConfigError`` / ``ValueError`` before any connection."""
    load_config_files()
    api_key = get_normalized_api_key()
    if not api_key:
        raise ValueError(get_missing_api_key_message())
    return api_key


def get_endpoint(override: str | None = None) -> str:
    """``--endpoint`` wins, then the layered ``endpoint`` setting, then the default.

    A blank resolved value does not fall through to a lower layer (an empty
    environment variable already blocked it). The built-in default still applies.
    """
    if override is not None and override.strip():
        return override.strip()
    value = resolve_setting("endpoint").value
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_ENDPOINT


def get_output_dir() -> Path:
    """Directory that receives ``NNNN-<slug>/`` folders.

    An absolute path (``~`` expanded) is used as-is. A relative path from a
    project ``.gdevdocs.toml`` resolves against that file's directory. Any other
    relative path, including the default ``temp/gdevdocs_mcp``, resolves against
    the git root of the cwd (or the cwd outside a git repo).
    """
    return _resolve_path("output_dir") or _anchor(Path(DEFAULT_OUTPUT_DIR), None)


def _resolve_path(key: str) -> Path | None:
    setting = resolve_setting(key)
    raw = setting.value.strip() if isinstance(setting.value, str) else ""
    return _anchor(Path(raw), setting.base_dir) if raw else None


def _anchor(path: Path, base_dir: Path | None) -> Path:
    path = path.expanduser()
    if path.is_absolute():
        return path
    return (base_dir or find_git_root() or Path.cwd()) / path
