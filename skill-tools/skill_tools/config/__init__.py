"""Configuration discovery and platform-specific cache path resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path, PureWindowsPath
from typing import Any

import yaml

from ..hooks.catalog import AGENTS as HOOK_AGENTS
from ..locations import project_root, pyproject_path
from ..models import ConfigError, SourceError
from ..source import GitHubSource, LocalSource

FB_DIR_ENV = "SKILL_TOOLS_FB_DIR"

DEFAULT_GITHUB_OWNER = "fdshg693"
DEFAULT_GITHUB_REPOSITORY = "ai"
DEFAULT_GITHUB_REF = "main"
DEFAULT_DESTINATION = ".claude/skills"
DEFAULT_SELF_SKILL = "claude-plugins/my-tools/skills/skill-tools-cli/SKILL.md"


@dataclass(frozen=True)
class SourceConfig:
    type: str
    path: Path | None = None
    owner: str = DEFAULT_GITHUB_OWNER
    repository: str = DEFAULT_GITHUB_REPOSITORY
    ref: str = DEFAULT_GITHUB_REF


@dataclass(frozen=True)
class IndexConfig:
    path: Path


@dataclass(frozen=True)
class FbConfig:
    path: Path


def _default_fb_config() -> FbConfig:
    return FbConfig(default_fb_path())


CLAUDE_SETTINGS_FILES = {
    "project": ".claude/settings.json",
    "local": ".claude/settings.local.json",
}


@dataclass(frozen=True)
class HooksConfig:
    """``hooks:`` settings: default agents and per-agent install overrides."""

    default_agents: tuple[str, ...] = ()
    destinations: dict[str, str] = field(default_factory=dict)
    claude_settings_file: str = "project"


@dataclass(frozen=True)
class SkillToolsConfig:
    source: SourceConfig
    index: IndexConfig
    destinations: dict[str, str]
    targets: dict[str, str] = field(default_factory=dict)
    target_destinations: dict[str, dict[str, str]] = field(default_factory=dict)
    hooks: HooksConfig = field(default_factory=HooksConfig)
    fb: FbConfig = field(default_factory=_default_fb_config)
    self_skill: str = DEFAULT_SELF_SKILL
    config_path: Path | None = None
    global_config_path: Path | None = None
    cwd_config_path: Path | None = None
    global_config_exists: bool = False

    def destination_for(self, canonical_id: str, target: str | None = None) -> str:
        if target is None:
            return self.destinations.get(canonical_id, DEFAULT_DESTINATION)
        return self.target_destinations.get(canonical_id, {}).get(
            target,
            self.targets.get(target, self.destinations.get(canonical_id, DEFAULT_DESTINATION)),
        )


def _cache_home() -> Path:
    override = os.environ.get("SKILL_TOOLS_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data).expanduser().resolve() / "skill-tools"
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache).expanduser().resolve() / "skill-tools"
    return Path.home() / ".cache" / "skill-tools"


def default_index_path() -> Path:
    return _cache_home() / "skill-index.json"


def default_fb_path() -> Path:
    """Feedback root beside a checkout, or under the cache when no project file is shipped."""

    if pyproject_path() is not None:
        return project_root() / "fb"
    return _cache_home() / "fb"


def user_config_path() -> Path:
    if os.name == "nt":
        app_data = os.environ.get("APPDATA")
        if app_data:
            return Path(app_data).expanduser().resolve() / "skill-tools" / "skill-tools.yaml"
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config).expanduser().resolve() / "skill-tools" / "skill-tools.yaml"
    return Path.home() / ".config" / "skill-tools" / "skill-tools.yaml"


def _embedded_default_data() -> dict[str, Any]:
    """Return the explicit defaults used when no config layer is available."""
    return {
        "source": {
            "type": "github",
            "owner": DEFAULT_GITHUB_OWNER,
            "repository": DEFAULT_GITHUB_REPOSITORY,
            "ref": DEFAULT_GITHUB_REF,
        },
        "index": {"path": str(default_index_path())},
        "fb": {"path": str(default_fb_path())},
        "self_skill": DEFAULT_SELF_SKILL,
        "skills": {},
    }


def default_config_text() -> str:
    """Return the user-facing config file containing all default values."""
    return yaml.safe_dump(
        _embedded_default_data(),
        sort_keys=False,
        allow_unicode=True,
    )


def initialize_user_config(
    path: Path | None = None,
    *,
    force: bool = False,
) -> tuple[Path, bool]:
    """Create the global config file if it does not exist.

    Returns the path and whether a file was created. This is intentionally an
    explicit operation because package installers do not reliably run Python
    post-install hooks for wheel-based installs.
    """
    target = (path or user_config_path()).expanduser().resolve()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and not force:
            return target, False
        target.write_text(default_config_text(), encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not create global config {target}: {exc}") from exc
    return target, True


def _safe_destination(destination: object) -> str:
    if not isinstance(destination, str) or not destination:
        raise ConfigError("destination must be a non-empty relative path")
    native = Path(destination)
    windows = PureWindowsPath(destination)
    if (
        native.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in native.parts
        or ".." in windows.parts
    ):
        raise ConfigError(f"destination must be a safe relative path: {destination!r}")
    return destination


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must contain a mapping")
    return data


def _copy_mapping(data: object) -> object:
    if isinstance(data, dict):
        return {key: _copy_mapping(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_copy_mapping(value) for value in data]
    return data


def _merge_mappings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = _copy_mapping(base)
    assert isinstance(merged, dict)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _merge_mappings(merged[key], value)
        else:
            merged[key] = _copy_mapping(value)
    return merged


def _merge_config_data(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = _merge_mappings(base, override)
    base_source = base.get("source")
    override_source = override.get("source")
    effective_source = merged.get("source")
    if (
        isinstance(base_source, dict)
        and isinstance(override_source, dict)
        and isinstance(effective_source, dict)
        and override_source.get("type") is not None
        and override_source.get("type") != base_source.get("type")
    ):
        irrelevant = (
            {"path"}
            if effective_source.get("type") == "github"
            else {
                "owner",
                "repository",
                "ref",
            }
        )
        merged["source"] = {
            key: value
            for key, value in effective_source.items()
            if key not in irrelevant or key in override_source
        }
    return merged


def _normalize_paths(data: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """Make paths from one config layer independent of the merge location."""
    normalized = _copy_mapping(data)
    assert isinstance(normalized, dict)
    source = normalized.get("source")
    if isinstance(source, dict) and isinstance(source.get("path"), str) and source["path"]:
        source_path = Path(source["path"]).expanduser()
        source["path"] = str(
            (base_dir / source_path).resolve()
            if not source_path.is_absolute()
            else source_path.resolve()
        )
    index = normalized.get("index")
    if isinstance(index, dict) and isinstance(index.get("path"), str) and index["path"]:
        index_path = Path(index["path"]).expanduser()
        index["path"] = str(
            (base_dir / index_path).resolve()
            if not index_path.is_absolute()
            else index_path.resolve()
        )
    feedback = normalized.get("fb")
    if isinstance(feedback, dict) and isinstance(feedback.get("path"), str) and feedback["path"]:
        feedback_path = Path(feedback["path"]).expanduser()
        feedback["path"] = str(
            (base_dir / feedback_path).resolve()
            if not feedback_path.is_absolute()
            else feedback_path.resolve()
        )
    return normalized


def _parse_source(data: object, base_dir: Path) -> SourceConfig:
    if not isinstance(data, dict):
        raise ConfigError("source must be a mapping")
    source_type = data.get("type")
    if source_type not in {"local", "github"}:
        raise ConfigError("source.type must be 'local' or 'github'")
    allowed = {"type", "path"} if source_type == "local" else {"type", "owner", "repository", "ref"}
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"source contains unknown keys: {', '.join(sorted(unknown))}")
    if source_type == "local":
        raw_path = data.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise ConfigError("source.path must be a non-empty path for a local source")
        source_path = Path(raw_path).expanduser()
        if not source_path.is_absolute():
            source_path = base_dir / source_path
        return SourceConfig(type="local", path=source_path.resolve())
    values = {
        key: data.get(key, default)
        for key, default in (
            ("owner", DEFAULT_GITHUB_OWNER),
            ("repository", DEFAULT_GITHUB_REPOSITORY),
            ("ref", DEFAULT_GITHUB_REF),
        )
    }
    if not all(isinstance(value, str) and value for value in values.values()):
        raise ConfigError("GitHub source owner, repository, and ref must be non-empty strings")
    return SourceConfig(type="github", **values)


def _parse_targets(data: object, filename: str) -> dict[str, str]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{filename}.targets must be a mapping")
    targets: dict[str, str] = {}
    for name, setting in data.items():
        if (
            not isinstance(name, str)
            or not name
            or not name[0].isalnum()
            or any(not (char.isalnum() or char in "_-") for char in name)
        ):
            raise ConfigError(f"{filename}.targets keys must be valid target names: {name!r}")
        if not isinstance(setting, dict) or set(setting) != {"destination"}:
            raise ConfigError(f"{filename}.targets[{name!r}] must contain only a destination")
        targets[name] = _safe_destination(setting["destination"])
    return targets


def _parse_destinations(
    data: object, filename: str
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    if data is None:
        return {}, {}
    if not isinstance(data, dict):
        raise ConfigError(f"{filename}.skills must be a mapping")
    destinations: dict[str, str] = {}
    target_destinations: dict[str, dict[str, str]] = {}
    for canonical_id, setting in data.items():
        if not isinstance(canonical_id, str) or not canonical_id:
            raise ConfigError(f"{filename}.skills keys must be non-empty canonical skill IDs")
        if not isinstance(setting, dict) or set(setting) - {"destination", "destinations"}:
            raise ConfigError(f"{filename}.skills[{canonical_id!r}] contains unknown keys")
        if "destination" in setting:
            destinations[canonical_id] = _safe_destination(setting["destination"])
        per_target = setting.get("destinations", {})
        if not isinstance(per_target, dict):
            raise ConfigError(f"{filename}.skills[{canonical_id!r}].destinations must be a mapping")
        target_destinations[canonical_id] = {}
        for target, destination in per_target.items():
            if not isinstance(target, str) or not target:
                raise ConfigError(
                    f"{filename}.skills[{canonical_id!r}] target names must be strings"
                )
            target_destinations[canonical_id][target] = _safe_destination(destination)
    return destinations, target_destinations


def _parse_self_skill(value: object) -> str:
    """Validate the canonical ID that the ``self`` selector expands to."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("self_skill must be a non-empty repository-relative path")
    native = Path(value)
    windows = PureWindowsPath(value)
    if (
        native.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or windows.root
        or ".." in native.parts
        or ".." in windows.parts
    ):
        raise ConfigError(f"self_skill must be a safe repository-relative path: {value!r}")
    return value


def _parse_hooks(data: object, filename: str) -> HooksConfig:
    if data is None:
        return HooksConfig()
    if not isinstance(data, dict):
        raise ConfigError(f"{filename}.hooks must be a mapping")
    unknown = set(data) - {"default_agents", "agents"}
    if unknown:
        raise ConfigError(f"{filename}.hooks contains unknown keys: {', '.join(sorted(unknown))}")
    raw_defaults = data.get("default_agents", [])
    if not isinstance(raw_defaults, list) or not all(
        isinstance(item, str) and item in HOOK_AGENTS for item in raw_defaults
    ):
        raise ConfigError(
            f"{filename}.hooks.default_agents must be a list of: {', '.join(HOOK_AGENTS)}"
        )
    agents = data.get("agents", {})
    if not isinstance(agents, dict):
        raise ConfigError(f"{filename}.hooks.agents must be a mapping")
    destinations: dict[str, str] = {}
    settings_file = "project"
    for agent, setting in agents.items():
        if agent not in HOOK_AGENTS:
            raise ConfigError(f"{filename}.hooks.agents has an unknown agent: {agent!r}")
        allowed = {"destination", "settings_file"} if agent == "claude" else {"destination"}
        if not isinstance(setting, dict) or set(setting) - allowed:
            raise ConfigError(
                f"{filename}.hooks.agents.{agent} may only contain: {', '.join(sorted(allowed))}"
            )
        if "destination" in setting:
            destination = _safe_destination(setting["destination"])
            if Path(destination).parts[0].casefold() == ".skill-tools":
                raise ConfigError(f"{filename}.hooks.agents.{agent}.destination overlaps metadata")
            destinations[agent] = destination.replace("\\", "/")
        if "settings_file" in setting:
            if setting["settings_file"] not in CLAUDE_SETTINGS_FILES:
                raise ConfigError(
                    f"{filename}.hooks.agents.claude.settings_file must be "
                    f"{' or '.join(CLAUDE_SETTINGS_FILES)}"
                )
            settings_file = setting["settings_file"]
    return HooksConfig(
        default_agents=tuple(dict.fromkeys(raw_defaults)),
        destinations=destinations,
        claude_settings_file=settings_file,
    )


def _parse_fb(data: object, path: Path | None) -> FbConfig:
    if data is None:
        return _default_fb_config()
    if not isinstance(data, dict):
        raise ConfigError("fb must be a mapping")
    unknown = set(data) - {"path"}
    if unknown:
        raise ConfigError(f"fb contains unknown keys: {', '.join(sorted(unknown))}")
    raw_path = data.get("path")
    if raw_path is None:
        return _default_fb_config()
    if not isinstance(raw_path, str) or not raw_path:
        raise ConfigError("fb.path must be a non-empty string")
    fb_path = Path(raw_path).expanduser()
    if not fb_path.is_absolute():
        fb_path = (path.parent if path is not None else Path.cwd()) / fb_path
    return FbConfig(fb_path.resolve())


def _parse_config(data: dict[str, Any], path: Path | None) -> SkillToolsConfig:
    allowed = {"source", "index", "fb", "skills", "targets", "hooks", "self_skill"}
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"configuration contains unknown keys: {', '.join(sorted(unknown))}")
    source = _parse_source(
        data.get(
            "source",
            {
                "type": "github",
                "owner": DEFAULT_GITHUB_OWNER,
                "repository": DEFAULT_GITHUB_REPOSITORY,
                "ref": DEFAULT_GITHUB_REF,
            },
        ),
        path.parent if path is not None else Path.cwd(),
    )

    index_data = data.get("index", {})
    if not isinstance(index_data, dict):
        raise ConfigError("index must be a mapping")
    unknown_index = set(index_data) - {"path"}
    if unknown_index:
        raise ConfigError(f"index contains unknown keys: {', '.join(sorted(unknown_index))}")
    raw_index_path = index_data.get("path")
    if raw_index_path is not None and (not isinstance(raw_index_path, str) or not raw_index_path):
        raise ConfigError("index.path must be a non-empty string")
    if raw_index_path is None:
        index_path = default_index_path()
    else:
        index_path = Path(raw_index_path).expanduser()
        if not index_path.is_absolute():
            index_path = (path.parent if path is not None else Path.cwd()) / index_path
        index_path = index_path.resolve()
    destinations, target_destinations = _parse_destinations(
        data.get("skills"), path.name if path else "skill-tools.yaml"
    )
    targets = _parse_targets(data.get("targets"), path.name if path else "skill-tools.yaml")
    unknown_targets = {
        target for per_target in target_destinations.values() for target in per_target
    } - set(targets)
    if unknown_targets:
        raise ConfigError(
            f"skill destinations reference unknown targets: {', '.join(sorted(unknown_targets))}"
        )
    return SkillToolsConfig(
        source=source,
        index=IndexConfig(index_path),
        destinations=destinations,
        targets=targets,
        target_destinations=target_destinations,
        hooks=_parse_hooks(data.get("hooks"), path.name if path else "skill-tools.yaml"),
        fb=_parse_fb(data.get("fb"), path),
        self_skill=_parse_self_skill(data.get("self_skill", DEFAULT_SELF_SKILL)),
        config_path=path,
    )


def load_config(config_path: Path | None = None, cwd: Path | None = None) -> SkillToolsConfig:
    """Resolve embedded, global, and CWD-specific configuration layers."""

    working_directory = (cwd or Path.cwd()).resolve()
    embedded = _embedded_default_data()

    # An explicit path is an escape hatch for CI and migration. Preserve its
    # historical behavior and do not merge it with the user's global config.
    if config_path is not None:
        selected = Path(config_path).expanduser().resolve()
        if not selected.is_file():
            raise ConfigError(f"configuration file does not exist: {selected}")
        data = _merge_config_data(embedded, _normalize_paths(_load_yaml(selected), selected.parent))
        return _parse_config(data, selected)

    if os.environ.get("SKILL_TOOLS_CONFIG"):
        selected = Path(os.environ["SKILL_TOOLS_CONFIG"]).expanduser().resolve()
        if not selected.is_file():
            raise ConfigError(f"configuration file does not exist: {selected}")
        data = _merge_config_data(embedded, _normalize_paths(_load_yaml(selected), selected.parent))
        return _parse_config(data, selected)

    global_path = user_config_path()
    cwd_path = working_directory / "skill-tools.yaml"
    global_exists = global_path.is_file()
    cwd_exists = cwd_path.is_file()

    data = embedded
    if global_exists:
        data = _merge_config_data(
            data, _normalize_paths(_load_yaml(global_path), global_path.parent)
        )
    if cwd_exists:
        data = _merge_config_data(data, _normalize_paths(_load_yaml(cwd_path), cwd_path.parent))

    selected = cwd_path if cwd_exists else global_path if global_exists else None
    config = _parse_config(data, selected)
    return replace(
        config,
        global_config_path=global_path,
        cwd_config_path=cwd_path,
        global_config_exists=global_exists,
    )


def create_source(config: SkillToolsConfig):
    """Instantiate the configured source; GitHub is resolved only for builds."""

    if config.source.type == "local":
        assert config.source.path is not None
        return LocalSource(config.source.path)
    return GitHubSource(config.source.owner, config.source.repository, config.source.ref)


def source_identity(config: SkillToolsConfig) -> dict[str, str]:
    """Return the configured source identity without resolving a GitHub commit."""

    if config.source.type == "local":
        assert config.source.path is not None
        return {"type": "local", "path": str(config.source.path)}
    return {
        "type": "github",
        "owner": config.source.owner,
        "repository": config.source.repository,
        "ref": config.source.ref,
    }


def apply_cli_overrides(
    config: SkillToolsConfig,
    *,
    source_type: str | None = None,
    repo: Path | None = None,
    github_owner: str | None = None,
    github_repository: str | None = None,
    github_ref: str | None = None,
    index_path: Path | None = None,
    cwd: Path | None = None,
) -> SkillToolsConfig:
    """Apply optional CLI overrides without inferring a source from CWD."""

    working_directory = (cwd or Path.cwd()).resolve()
    effective_type = source_type or config.source.type
    github_overrides = (github_owner, github_repository, github_ref)
    if source_type == "local" and repo is None:
        raise SourceError("--repo is required with --source local")
    if repo is not None and effective_type != "local":
        raise SourceError("--repo can only be used with --source local")

    source = config.source
    if effective_type == "local" and (source_type == "local" or repo is not None):
        assert repo is not None
        source = SourceConfig(type="local", path=Path(repo).expanduser().resolve())
    elif source_type == "github" or (
        effective_type == "github" and any(value is not None for value in github_overrides)
    ):
        current_github = config.source.type == "github"
        source = SourceConfig(
            type="github",
            owner=github_owner or (config.source.owner if current_github else DEFAULT_GITHUB_OWNER),
            repository=github_repository
            or (config.source.repository if current_github else DEFAULT_GITHUB_REPOSITORY),
            ref=github_ref or (config.source.ref if current_github else DEFAULT_GITHUB_REF),
        )

    updated = replace(config, source=source)
    if index_path is None:
        return updated
    resolved_index = Path(index_path).expanduser()
    if not resolved_index.is_absolute():
        resolved_index = working_directory / resolved_index
    return replace(updated, index=IndexConfig(resolved_index.resolve()))
