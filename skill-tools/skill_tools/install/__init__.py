"""Install plans, manifests, and bundle copy policy."""

from __future__ import annotations

_EXPORTS = {
    "installer": (
        "JOURNAL_SCHEMA_VERSIONS",
        "InstallPlan",
        "manifest_path",
        "load_project_manifest",
        "recover_transaction",
        "resolve_install_target",
        "build_plan",
        "execute_file_transaction",
        "execute_install",
        "execute_remove",
    ),
    "manifest": (
        "MANIFEST_SCHEMA_VERSION",
        "MANIFEST_RELATIVE_PATH",
        "empty_manifest",
        "hook_file_paths",
        "validate_manifest",
        "load_manifest",
        "normalized_source",
        "make_entry",
        "resolve_install_path",
        "verify_entry",
        "write_manifest",
    ),
    "policy": (
        "GITIGNORE_PATH",
        "INCLUDE_PATH",
        "DEFAULT_EXCLUDED_DIRECTORIES",
        "DEFAULT_EXCLUDES",
        "BundlePolicy",
        "load_bundle_policy",
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
    "JOURNAL_SCHEMA_VERSIONS",
    "InstallPlan",
    "manifest_path",
    "load_project_manifest",
    "recover_transaction",
    "resolve_install_target",
    "build_plan",
    "execute_file_transaction",
    "execute_install",
    "execute_remove",
    "MANIFEST_SCHEMA_VERSION",
    "MANIFEST_RELATIVE_PATH",
    "empty_manifest",
    "hook_file_paths",
    "validate_manifest",
    "load_manifest",
    "normalized_source",
    "make_entry",
    "resolve_install_path",
    "verify_entry",
    "write_manifest",
    "GITIGNORE_PATH",
    "INCLUDE_PATH",
    "DEFAULT_EXCLUDED_DIRECTORIES",
    "DEFAULT_EXCLUDES",
    "BundlePolicy",
    "load_bundle_policy",
]
