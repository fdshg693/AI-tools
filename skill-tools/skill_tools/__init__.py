"""Canonical source, catalog, index, and search library for skill-tools."""

from .catalog import discover_catalog, discover_bundles, select_records
from .config import (
    create_source,
    default_config_text,
    default_index_path,
    initialize_user_config,
    load_config,
    user_config_path,
)
from .hooks.catalog import filter_hooks, load_hook_catalog, parse_hook_catalog
from .index.build import INDEX_SCHEMA_VERSION, make_index, read_index, write_index
from .models import (
    CatalogError,
    ConfigError,
    EmbeddingError,
    HookAgent,
    HookFile,
    HookRecord,
    IndexError,
    InstallError,
    SearchResult,
    SkillBundle,
    SkillRecord,
    SkillToolsError,
    SourceError,
)
from .repo_tools.descriptions import resolve_description
from .repo_tools.load import (
    DescriptionLocator,
    RepoTool,
    install_repo_tools,
    load_repo_tools,
    parse_locator,
    parse_repo_tools,
    resolve_install_root,
    select_repo_tools,
)
from .source import display_skill_path

__all__ = [
    "CatalogError",
    "ConfigError",
    "DescriptionLocator",
    "EmbeddingError",
    "HookAgent",
    "HookFile",
    "HookRecord",
    "INDEX_SCHEMA_VERSION",
    "IndexError",
    "InstallError",
    "RepoTool",
    "SearchResult",
    "SkillBundle",
    "SkillRecord",
    "SkillToolsError",
    "SourceError",
    "create_source",
    "default_config_text",
    "default_index_path",
    "discover_bundles",
    "discover_catalog",
    "filter_hooks",
    "display_skill_path",
    "initialize_user_config",
    "install_repo_tools",
    "load_config",
    "load_hook_catalog",
    "load_repo_tools",
    "make_index",
    "parse_hook_catalog",
    "parse_locator",
    "parse_repo_tools",
    "read_index",
    "resolve_description",
    "resolve_install_root",
    "select_records",
    "select_repo_tools",
    "user_config_path",
    "write_index",
]
