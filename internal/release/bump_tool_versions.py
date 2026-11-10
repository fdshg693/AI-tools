"""Bump manifest versions for registered repo-tools.yaml CLI tools.

For each first-class tool registered in ``repo-tools.yaml``, checks whether any
of the given paths (default: currently staged files) live under that tool's
folder. If so, and the tool's manifest version still matches ``HEAD``, bumps
its patch version exactly once and stages the manifest file.

Version storage stays in each tool's own manifest:
- Python tools: ``pyproject.toml`` -> ``[project].version`` via ``uv version``
- Node tools: ``package.json`` -> ``version`` via ``pnpm version``
  (``--no-git-checks`` so lefthook can bump during a dirty pre-commit tree)

If the manifest version already differs from ``HEAD`` (for example a manual
minor/major bump), the script respects that explicit change and skips the auto
bump. New manifests added in the current commit are also skipped after their
initial version is set.

Run standalone via ``just --justfile tools/internal/justfile tool-version-bump``
or let lefthook pass the staged file list.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_TOOLS_YAML_PATH = REPO_ROOT / "repo-tools.yaml"


class ToolVersionError(RuntimeError):
    """Raised when a registered tool's manifest cannot be processed safely."""


@dataclass(frozen=True)
class RegisteredTool:
    key: str
    path: str


@dataclass(frozen=True)
class ToolManifest:
    tool: RegisteredTool
    kind: Literal["python", "node"]
    manifest_path: Path
    manifest_rel_posix: str
    version: str


def load_registered_tools() -> list[RegisteredTool]:
    data = yaml.safe_load(REPO_TOOLS_YAML_PATH.read_text(encoding="utf-8"))
    return [RegisteredTool(key=key, path=value["path"]) for key, value in data["tools"].items()]


def parse_pyproject_version(text: str) -> str | None:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    version = project.get("version")
    if version is None:
        return None
    value = str(version).strip()
    return value or None


def parse_package_json_version(text: str) -> str | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    version = data.get("version")
    if version is None:
        return None
    value = str(version).strip()
    return value or None


def _manifest_candidates(tool: RegisteredTool) -> list[ToolManifest]:
    tool_dir = REPO_ROOT / tool.path
    candidates: list[ToolManifest] = []

    pyproject = tool_dir / "pyproject.toml"
    if pyproject.is_file():
        version = parse_pyproject_version(pyproject.read_text(encoding="utf-8"))
        if version is None:
            raise ToolVersionError(
                f"{tool.key}: {tool.path}/pyproject.toml has no [project].version"
            )
        candidates.append(
            ToolManifest(
                tool=tool,
                kind="python",
                manifest_path=pyproject,
                manifest_rel_posix=pyproject.relative_to(REPO_ROOT).as_posix(),
                version=version,
            )
        )

    package_json = tool_dir / "package.json"
    if package_json.is_file():
        version = parse_package_json_version(package_json.read_text(encoding="utf-8"))
        if version is None:
            raise ToolVersionError(f"{tool.key}: {tool.path}/package.json has no version")
        candidates.append(
            ToolManifest(
                tool=tool,
                kind="node",
                manifest_path=package_json,
                manifest_rel_posix=package_json.relative_to(REPO_ROOT).as_posix(),
                version=version,
            )
        )

    return candidates


def resolve_manifest(tool: RegisteredTool) -> ToolManifest:
    candidates = _manifest_candidates(tool)
    if not candidates:
        raise ToolVersionError(
            f"{tool.key}: expected exactly one manifest at {tool.path}/pyproject.toml "
            f"or {tool.path}/package.json, found none"
        )
    if len(candidates) > 1:
        names = ", ".join(candidate.manifest_rel_posix for candidate in candidates)
        raise ToolVersionError(
            f"{tool.key}: expected exactly one versioned manifest under {tool.path}, found {names}"
        )
    return candidates[0]


def staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--cached", "--diff-filter=ACMR"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _git_show(rel_posix_path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel_posix_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def head_version(manifest: ToolManifest) -> str | None:
    head_text = _git_show(manifest.manifest_rel_posix)
    if head_text is None:
        return None
    if manifest.kind == "python":
        return parse_pyproject_version(head_text)
    return parse_package_json_version(head_text)


def tool_changed(tool_path: str, changed_posix: list[str]) -> bool:
    prefix = f"{tool_path}/"
    return any(path == tool_path or path.startswith(prefix) for path in changed_posix)


def should_bump(manifest: ToolManifest) -> bool:
    previous = head_version(manifest)
    if previous is None:
        return False
    return previous == manifest.version


def bump_command(manifest: ToolManifest) -> list[str]:
    if manifest.kind == "python":
        return ["uv", "version", "--bump", "patch", "--frozen"]
    return ["pnpm", "version", "patch", "--no-git-tag-version", "--no-git-checks"]


def bump_manifest(manifest: ToolManifest, *, dry_run: bool) -> str:
    command = bump_command(manifest)
    if dry_run:
        return f"{manifest.tool.path}: would bump {manifest.manifest_rel_posix} via {' '.join(command)}"

    result = subprocess.run(
        command,
        cwd=REPO_ROOT / manifest.tool.path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ToolVersionError(
            f"failed to bump version for {manifest.tool.path} via {' '.join(command)}:\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )

    add_result = subprocess.run(
        ["git", "add", "--", manifest.manifest_rel_posix],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if add_result.returncode != 0:
        raise ToolVersionError(
            f"failed to stage {manifest.manifest_rel_posix}:\n"
            f"{add_result.stderr.strip() or add_result.stdout.strip()}"
        )

    return f"{manifest.tool.path}: {result.stdout.strip() or result.stderr.strip()}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tool-version-bump",
        description=(
            "Bump patch versions for repo-tools.yaml registered tools whose staged "
            "files changed under that tool directory."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print which tool manifests would be bumped without modifying files",
    )
    parser.add_argument("paths", nargs="*", help="changed paths (defaults to staged files)")
    return parser


def run(changed: list[str], *, dry_run: bool) -> int:
    changed_posix = [Path(path).as_posix() for path in changed]
    results: list[str] = []

    for tool in load_registered_tools():
        if not tool_changed(tool.path, changed_posix):
            continue
        manifest = resolve_manifest(tool)
        if not should_bump(manifest):
            continue
        results.append(bump_manifest(manifest, dry_run=dry_run))

    if results:
        for line in results:
            print(line)
    else:
        print("No registered tool manifests needed a version bump.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    changed = args.paths if args.paths else staged_files()
    try:
        return run(changed, dry_run=args.dry_run)
    except ToolVersionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
