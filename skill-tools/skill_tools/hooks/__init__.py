"""Agent hook catalog, installation, and registration."""

from __future__ import annotations

from .catalog import (
    REPO_HOOKS_FILENAME,
    CATALOG_SCHEMA_VERSION,
    AGENTS,
    RUNNERS,
    parse_hook_catalog,
    load_hook_catalog,
    filter_hooks,
    hook_payload,
)

_EXPORTS = {
    "install": (
        "HookTarget",
        "HookChangeSet",
        "parse_agents",
        "ensure_installable",
        "select_install_targets",
        "select_managed_hooks",
        "apply_hook_changes",
    ),
    "registrars": (
        "DEFAULT_INSTALL_DIRS",
        "install_dir_for",
        "registration_file_for",
        "entry_hash",
        "build_entry",
        "RegistrationDocument",
    ),
}

_BY_NAME = {name: module for module, names in _EXPORTS.items() for name in names}


def __getattr__(name: str):
    module_name = _BY_NAME.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_BY_NAME))


__all__ = [
    "REPO_HOOKS_FILENAME",
    "CATALOG_SCHEMA_VERSION",
    "AGENTS",
    "RUNNERS",
    "parse_hook_catalog",
    "load_hook_catalog",
    "filter_hooks",
    "hook_payload",
    "HookTarget",
    "HookChangeSet",
    "parse_agents",
    "ensure_installable",
    "select_install_targets",
    "select_managed_hooks",
    "apply_hook_changes",
    "DEFAULT_INSTALL_DIRS",
    "install_dir_for",
    "registration_file_for",
    "entry_hash",
    "build_entry",
    "RegistrationDocument",
]
