"""Ensure every SKILL.md in the repo declares a non-empty meta.version.

Walks the whole repo (not just marketplace-listed plugins) for SKILL.md files.
Any file whose frontmatter is missing meta.version, or has it set to an empty
value, gets it patched in-place to "1.0.0". Files that already declare a
non-empty version are left untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

from skill.util.skill_frontmatter import find_skill_md_files, read_frontmatter
from skill.util.skill_meta_version import DEFAULT_VERSION, ensure_meta_version, has_version

REPO_ROOT = Path(__file__).resolve().parents[4]


def main() -> None:
    updated = 0
    checked = 0

    for skill_md_path in find_skill_md_files(REPO_ROOT):
        rel_path = skill_md_path.relative_to(REPO_ROOT)
        frontmatter = read_frontmatter(skill_md_path)
        if frontmatter is None:
            print(f"warning: skipping {rel_path} (no valid frontmatter)", file=sys.stderr)
            continue

        checked += 1
        if has_version(frontmatter.data):
            continue

        new_raw, changed = ensure_meta_version(frontmatter.raw, DEFAULT_VERSION)
        if not changed:
            continue

        skill_md_path.write_text(frontmatter.with_raw(new_raw), encoding="utf-8")
        updated += 1
        print(f"set meta.version={DEFAULT_VERSION} in {rel_path}")

    print(f"Checked {checked} SKILL.md files, updated {updated}.")


if __name__ == "__main__":
    main()
