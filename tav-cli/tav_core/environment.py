"""Settings & credentials: layered config resolution, the Tavily client, toggles.

Everything that reads the process environment or a config file lives here, so
changing how the CLI discovers its API key, output directory, or logging toggles
is a one-file edit. Resolution (highest precedence first; see README
"設定とパス解決" and ``docs/repo-wide/tool-conventions.md``):

1. Process environment variables (``TAVILY_*``), even when set to empty.
2. Project config ``.tav.toml``, searched from the cwd up to the git root
   (inclusive; outside a git repo only the cwd). The nearest file wins per key.
3. Global config ``<config home>/config.toml`` (``$TAV_CONFIG_HOME``, else
   ``$XDG_CONFIG_HOME/tav``, else ``~/.config/tav``).
4. Built-in defaults.

``api_key`` is accepted only from the environment or the global config — a
project file may be committed, so a key there is rejected with an error.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tavily import TavilyClient


API_KEY_ENV = "TAVILY_API_KEY"
OUTPUT_DIR_ENV = "TAVILY_OUTPUT_DIR"
WRITE_LOG_ENV = "TAVILY_WRITE_LOG"
SHOW_LOG_PATH_ENV = "TAVILY_SHOW_LOG_PATH"
CONFIG_HOME_ENV = "TAV_CONFIG_HOME"
LOG_DIR_ENV = "TAVILY_LOG_DIR"
DEFAULT_OUTPUT_DIR = "temp/web"
DEFAULT_LOG_SUBDIR = ".logs"

PROJECT_CONFIG_NAME = ".tav.toml"
GLOBAL_CONFIG_NAME = "config.toml"

TAV_CLI_ROOT = Path(__file__).resolve().parent.parent

# config-file key -> (env var, expected TOML type)
SETTINGS: dict[str, tuple[str, type]] = {
    "api_key": (API_KEY_ENV, str),
    "output_dir": (OUTPUT_DIR_ENV, str),
    "log_dir": (LOG_DIR_ENV, str),
    "write_log": (WRITE_LOG_ENV, bool),
    "show_log_path": (SHOW_LOG_PATH_ENV, bool),
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
    source: str  # "env:<NAME>" | absolute config-file path | "default"
    base_dir: Path | None  # directory relative paths resolve against (project files only)


def global_config_path() -> Path:
    override = os.getenv(CONFIG_HOME_ENV, "").strip()
    if override:
        return Path(override).expanduser() / GLOBAL_CONFIG_NAME
    xdg = os.getenv("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "tav" / GLOBAL_CONFIG_NAME


def find_git_root(start: Path | None = None) -> Path | None:
    """Nearest ancestor (inclusive) holding ``.git`` — a dir, or a file for worktrees."""
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        if (directory / ".git").exists():
            return directory
    return None


def project_config_paths(cwd: Path | None = None) -> list[Path]:
    """Existing ``.tav.toml`` files from the cwd up to the git root, nearest first."""
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
    for key, value in values.items():
        if key not in SETTINGS:
            allowed = ", ".join(SETTINGS)
            raise ConfigError(f"設定ファイル {path} の未知のキー {key!r}(使えるキー: {allowed})")
        if scope == "project" and key in GLOBAL_ONLY_SETTINGS:
            raise ConfigError(
                f"設定ファイル {path} に {key!r} は書けません(コミットされうるため)。"
                f"環境変数 {SETTINGS[key][0]} かグローバル設定 {global_config_path()} に置いてください。"
            )
        expected = SETTINGS[key][1]
        if not isinstance(value, expected):
            raise ConfigError(
                f"設定ファイル {path} の {key!r} は {expected.__name__} である必要があります"
                f"(実際: {type(value).__name__})"
            )
    return ConfigFile(path=path.resolve(), scope=scope, values=values)


def load_config_files(cwd: Path | None = None) -> list[ConfigFile]:
    """All config files that exist, in precedence order (nearest project → global)."""
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
            # Only a project file anchors relative paths to itself; a global value
            # like "temp/web" means "in each repo", so it falls through to the git root.
            base_dir = config.path.parent if config.scope == "project" else None
            return ResolvedSetting(config.values[key], str(config.path), base_dir)
    return ResolvedSetting(None, "default", None)


def load_environment() -> list[str]:
    """Validate every config file in reach and return their paths (precedence order)."""
    return [str(config.path) for config in load_config_files()]


def setting_sources() -> dict[str, str]:
    """Where each setting came from — recorded in the audit log for provenance."""
    return {key: resolve_setting(key).source for key in SETTINGS}


def get_normalized_api_key() -> str:
    value = resolve_setting("api_key").value
    return value.strip() if isinstance(value, str) else ""


def get_output_dir() -> Path:
    """Base directory for ``--topic`` output.

    Resolution base (IMPORTANT — this is the source of truth for the contract):

    - An **absolute** value (``~`` expanded) is used verbatim.
    - A **relative** value from a project ``.tav.toml`` resolves against **that
      file's directory**.
    - Any other **relative** value (global ``config.toml``, ``TAVILY_OUTPUT_DIR``,
      or the ``temp/web`` default) resolves against the **git root** of the cwd,
      or the cwd itself outside a git repo. So running from any subdirectory of a
      repo still lands in ``<repo>/temp/web/<topic>/``.
    """
    return _resolve_path("output_dir") or _anchor(Path(DEFAULT_OUTPUT_DIR), None)


def get_log_dir() -> Path:
    """Directory for the audit logs ``<script>-log.json``.

    ``log_dir`` / ``TAVILY_LOG_DIR``, resolved with the same rules as
    ``get_output_dir()``. Unset or blank -> ``<output_dir>/.logs`` so logs land
    next to the output of the project being worked on (the leading dot keeps it
    clear of ``--topic`` folders, whose names are slugs).
    """
    return _resolve_path("log_dir") or get_output_dir() / DEFAULT_LOG_SUBDIR


def _resolve_path(key: str) -> Path | None:
    """A path setting resolved per the anchoring rules; ``None`` when unset/blank."""
    setting = resolve_setting(key)
    raw = setting.value.strip() if isinstance(setting.value, str) else ""
    return _anchor(Path(raw), setting.base_dir) if raw else None


def _anchor(path: Path, base_dir: Path | None) -> Path:
    path = path.expanduser()
    if path.is_absolute():
        return path
    return (base_dir or find_git_root() or Path.cwd()) / path


_FALSEY_ENV_VALUES = {"", "false", "0", "no", "off"}


def _flag(key: str, *, default: bool = True) -> bool:
    """Resolve a boolean toggle.

    A config file must hold a TOML boolean. An env var uses the shared falsey
    convention: ``false`` / ``0`` / ``no`` / ``off`` / empty (case-insensitive)
    read as ``False``; anything else reads as ``True``. Unset everywhere is
    ``default``.
    """
    value = resolve_setting(key).value
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() not in _FALSEY_ENV_VALUES


def should_write_log() -> bool:
    """Whether to write ``logs/<script>-log.json`` (``write_log`` / ``TAVILY_WRITE_LOG``).

    Default (unset) is ``True`` — the historical always-on behavior.
    """
    return _flag("write_log")


def should_show_log_path() -> bool:
    """Whether to echo the "Wrote full log to <path>" notice (``show_log_path`` / ``TAVILY_SHOW_LOG_PATH``).

    Default (unset) is ``True``. This toggles ONLY the stderr ``DIAGNOSTIC`` notice
    for the *audit log* path, and only when an audit log is actually written
    (``should_write_log()``). Result/output file path notices are always shown —
    they point to the records the caller asked for — and the files themselves are
    unaffected.
    """
    return _flag("show_log_path")


def get_missing_api_key_message() -> str:
    """Rule-3 diagnosis: every place looked at, and why each gave nothing."""
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
        f"(プロジェクト設定 {PROJECT_CONFIG_NAME} からは api_key を読みません)"
    )


def create_tavily_client() -> tuple[TavilyClient, list[str]]:
    """Return the client and the config files in reach. ``ValueError`` (incl.
    ``ConfigError``) means the key is missing or a config file is unusable."""
    config_files = load_environment()
    api_key = get_normalized_api_key()
    if not api_key:
        raise ValueError(get_missing_api_key_message())
    return TavilyClient(api_key=api_key), config_files
