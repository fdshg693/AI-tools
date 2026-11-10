"""Ensure every SKILL.md in the repo declares a non-empty meta.description.

meta.description is an admin-only note for humans maintaining the skill
catalog (ignored by AI agents at skill-invocation time — that's the
top-level `description` field). Walks the whole repo (not just
marketplace-listed plugins) for SKILL.md files. Any file whose frontmatter is
missing meta.description, or has it set to an empty value, gets it patched
in-place to "no description". Files that already declare a non-empty
meta.description are left untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

from skill.util.skill_frontmatter import find_skill_md_files, read_frontmatter
from skill.util.skill_meta_description import (
    DEFAULT_DESCRIPTION,
    ensure_meta_description,
    has_description,
)

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
        if has_description(frontmatter.data):
            continue

        new_raw, changed = ensure_meta_description(frontmatter.raw, DEFAULT_DESCRIPTION)
        if not changed:
            continue

        skill_md_path.write_text(frontmatter.with_raw(new_raw), encoding="utf-8")
        updated += 1
        print(f"set meta.description={DEFAULT_DESCRIPTION!r} in {rel_path}")

    print(f"Checked {checked} SKILL.md files, updated {updated}.")


if __name__ == "__main__":
    main()
