"""Fail if a SKILL.md's requires_repo_tools/requires_install mentions a
tools/-rooted path that isn't registered (or is stale) in repo-tools.yaml.

meta-plugins/** is excluded: its SKILL.md files reuse requires_repo_tools to mean
"files this meta-skill documents" rather than "CLI dependency" (see
docs/repo-wide/tool-companion-skills.md), so it legitimately
references arbitrary repo files (justfile, lefthook.yml, pyproject.toml, ...)
that have nothing to do with this registry. tools/internal/** is also
excluded: those are internal repo-maintenance scripts, never something a
skill's user installs.

Run standalone via `just --justfile tools/internal/justfile
skill-repo-tools-check`, or wire into lefthook on SKILL.md/repo-tools.yaml
changes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from skill.util.repo_tools_registry import load_repo_tools
from skill.util.skill_frontmatter import find_skill_md_files, read_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[4]
EXCLUDED_PREFIXES = ("meta-plugins/", "tools/internal/")
FIELDS = ("requires_repo_tools", "requires_install")
TOOLS_PATH_PATTERN = re.compile(r"tools/[\w.-]+(?:/[\w.-]+)?")


def find_unregistered_tool_paths(
    skill_md_paths: list[Path] | None = None,
) -> list[tuple[str, str]]:
    """Return (skill_md_rel_posix, unregistered_path) pairs."""
    known_paths = {tool["path"] for tool in load_repo_tools().values()}
    paths = skill_md_paths if skill_md_paths is not None else find_skill_md_files(REPO_ROOT)

    failures: list[tuple[str, str]] = []
    for skill_md_path in paths:
        rel_posix = skill_md_path.relative_to(REPO_ROOT).as_posix()
        if any(rel_posix.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            continue

        frontmatter = read_frontmatter(skill_md_path)
        if frontmatter is None:
            continue
        meta = frontmatter.data.get("meta")
        if not isinstance(meta, dict):
            continue

        seen: set[str] = set()
        for field in FIELDS:
            value = meta.get(field)
            if not isinstance(value, str):
                continue
            for candidate in TOOLS_PATH_PATTERN.findall(value):
                if candidate.startswith("tools/internal/") or candidate in known_paths:
                    continue
                if candidate not in seen:
                    seen.add(candidate)
                    failures.append((rel_posix, candidate))
    return failures


def main(argv: list[str]) -> int:
    failures = find_unregistered_tool_paths()

    if failures:
        print(
            "SKILL.md references a tools/ path that isn't registered in repo-tools.yaml:",
            file=sys.stderr,
        )
        for rel_posix, bad_path in failures:
            print(f"  - {rel_posix}: {bad_path}", file=sys.stderr)
        print(
            "Register the tool in repo-tools.yaml (if it's a new CLI dependency), "
            "or fix the path if it's a typo or a stale rename.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
