"""Bump meta.version on SKILL.md files flagged by check_skill_version_bump.py.

Bumps only the trailing numeric segment (``1.2.3`` -> ``1.2.4``), dropping any
pre-release/build suffix stuck to it (``1.2.3-beta`` -> ``1.2.4``). With no
arguments, targets exactly the staged SKILL.md files that
check_skill_version_bump.py would currently reject (same detection logic,
shared via skill/util/skill_version_bump_check.py). Explicit path arguments
bump those files unconditionally, regardless of staged/HEAD comparison.
"""

from __future__ import annotations

import sys
from pathlib import Path

from skill.util.skill_frontmatter import read_frontmatter
from skill.util.skill_meta_field import set_meta_field
from skill.util.skill_version_bump import bump_last_numeric_segment
from skill.util.skill_version_bump_check import REPO_ROOT, find_unbumped_skill_md


def main(argv: list[str]) -> int:
    raw_paths = argv[1:]
    rel_paths = raw_paths if raw_paths else find_unbumped_skill_md(None)

    if not rel_paths:
        print("No SKILL.md files need a version bump.")
        return 0

    bumped = 0
    failures = 0

    for raw_path in rel_paths:
        abs_path = Path(raw_path)
        if not abs_path.is_absolute():
            abs_path = REPO_ROOT / abs_path

        frontmatter = read_frontmatter(abs_path)
        if frontmatter is None:
            print(f"error: {raw_path}: no valid frontmatter", file=sys.stderr)
            failures += 1
            continue

        current_version = str(frontmatter.data.get("meta", {}).get("version", "")).strip()
        if not current_version:
            print(f"error: {raw_path}: no meta.version to bump", file=sys.stderr)
            failures += 1
            continue

        new_version = bump_last_numeric_segment(current_version)
        if new_version is None:
            print(
                f"error: {raw_path}: meta.version {current_version!r} has no "
                "trailing numeric segment to bump",
                file=sys.stderr,
            )
            failures += 1
            continue

        new_raw, changed = set_meta_field(frontmatter.raw, "version", new_version)
        if not changed:
            continue

        abs_path.write_text(frontmatter.with_raw(new_raw), encoding="utf-8")
        bumped += 1
        print(f"bumped {raw_path}: {current_version} -> {new_version}")

    print(f"Bumped {bumped} SKILL.md file(s), {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
