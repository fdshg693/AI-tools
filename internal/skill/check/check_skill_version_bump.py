"""Fail if a tracked SKILL.md's content changed without a meta.version bump.

For each given SKILL.md path (defaults to the currently staged SKILL.md files
when run with no arguments), reports whether meta.version was bumped when the
rest of the frontmatter/body changed. Detection itself lives in
skill/util/skill_version_bump_check.py, shared with bump_skill_versions.py so
the "needs a bump" list is identical between the check and the auto-fixer.

Run standalone via `just --justfile tools/internal/justfile
skill-version-bump-check`, or wired into lefthook with the staged file list.
"""

from __future__ import annotations

import sys

from skill.util.skill_version_bump_check import find_unbumped_skill_md


def main(argv: list[str]) -> int:
    paths = argv[1:] if len(argv) > 1 else None
    failures = find_unbumped_skill_md(paths)

    if failures:
        print("meta.version must be bumped when SKILL.md content changes:", file=sys.stderr)
        for rel_posix in failures:
            print(f"  - {rel_posix}", file=sys.stderr)
        print(
            "Bump meta.version in the frontmatter by hand (e.g. 1.0.0 -> 1.0.1), "
            "or run `just --justfile tools/internal/justfile skill-version-bump` to bump "
            "all of the files above automatically (drops any pre-release suffix, "
            "e.g. 1.2.3-beta -> 1.2.4).",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
