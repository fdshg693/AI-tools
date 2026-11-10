"""Fail if repo-tools.yaml requires_tools edges are invalid or drift.

Checks: target is a key in the same file, kind is library/subprocess/family,
no extra-repo names, no self-edges, and library edges match uv workspace
deps in that tool's pyproject.toml (both directions). A registered tool
without pyproject.toml is skipped unless it declared a library edge.

Does not rewrite files. Run via the same just recipe as
check_skill_repo_tools.py (`skill-repo-tools-check`).
"""

from __future__ import annotations

import sys
from pathlib import Path

from skill.util.repo_tools_registry import (
    REPO_ROOT,
    REQUIRES_TOOLS_KINDS,
    RequiresToolsError,
    load_repo_tools,
    requires_tools_of,
)
from skill.util.workspace_deps import (
    load_pyproject,
    tool_keys_by_project_name,
    workspace_dependency_names,
)

KINDS_DISPLAY = " / ".join(sorted(REQUIRES_TOOLS_KINDS))


def find_relation_failures(
    tools: dict | None = None,
    repo_root: Path | None = None,
) -> list[str]:
    """Return human-readable failure lines (no header)."""
    root = repo_root if repo_root is not None else REPO_ROOT
    registry = tools if tools is not None else load_repo_tools()
    name_to_key = tool_keys_by_project_name(registry, root)
    failures: list[str] = []

    for tool_name, entry in registry.items():
        if not isinstance(entry, dict):
            failures.append(f"{tool_name}: entry must be a mapping")
            continue
        try:
            declared = requires_tools_of(entry)
        except RequiresToolsError as exc:
            failures.append(f"{tool_name}: {exc}")
            continue

        declared_library: set[str] = set()
        for target, kind in declared.items():
            if target == tool_name:
                failures.append(f"{tool_name}: requires_tools cannot list itself")
                continue
            if target not in registry:
                failures.append(
                    f"{tool_name}: unknown tool {target!r} (repo-external deps "
                    "belong in skill requires_install / requires_env, not requires_tools)"
                )
                continue
            if kind not in REQUIRES_TOOLS_KINDS:
                failures.append(
                    f"{tool_name}: invalid kind {kind!r} for {target!r} (must be {KINDS_DISPLAY})"
                )
                continue
            if kind == "library":
                declared_library.add(target)

        path = entry.get("path")
        if not isinstance(path, str) or not path:
            if declared_library:
                failures.append(
                    f"{tool_name}: library requires_tools needs a path to a pyproject.toml"
                )
            continue

        pyproject_path = root / path / "pyproject.toml"
        data = load_pyproject(pyproject_path)
        if data is None:
            if declared_library:
                failures.append(
                    f"{tool_name}: library edge declared but {path}/pyproject.toml is missing"
                )
            continue

        workspace_keys: set[str] = set()
        for pkg_name in workspace_dependency_names(data):
            mapped = name_to_key.get(pkg_name)
            if mapped is None:
                failures.append(
                    f"{tool_name}: workspace dependency {pkg_name!r} is not a registered "
                    "tool (add it to repo-tools.yaml if it is first-class)"
                )
                continue
            workspace_keys.add(mapped)

        for extra in sorted(declared_library - workspace_keys):
            failures.append(
                f"{tool_name}: library edge to {extra!r} has no matching workspace "
                f"dependency in {path}/pyproject.toml"
            )
        for missing in sorted(workspace_keys - declared_library):
            failures.append(
                f"{tool_name}: workspace dependency {missing!r} is not declared "
                "as requires_tools library"
            )

    return failures


def main(argv: list[str]) -> int:
    del argv
    failures = find_relation_failures()
    if not failures:
        return 0

    print("repo-tools.yaml requires_tools is invalid:", file=sys.stderr)
    for line in failures:
        print(f"  - {line}", file=sys.stderr)
    print(
        "Fix the edge (key must exist in repo-tools.yaml; kind must be "
        f"{KINDS_DISPLAY}), or align library edges with that tool's "
        "pyproject.toml workspace dependencies.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
