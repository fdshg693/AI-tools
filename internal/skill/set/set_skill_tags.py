"""Ensure every SKILL.md in the repo declares a meta.tag array.

Walks the whole repo (not just marketplace-listed plugins) for SKILL.md
files. Any file whose frontmatter is missing meta.tag gets it patched
in-place to an empty array ([]). Files that already declare meta.tag
(including an empty one) are left untouched. See skill-tags.yaml (repo root)
for the allowed tag values; this script does not assign any.
"""

from __future__ import annotations

import sys
from pathlib import Path

from skill.util.skill_frontmatter import find_skill_md_files, read_frontmatter
from skill.util.skill_meta_tag import DEFAULT_TAG_LITERAL, ensure_meta_tag, has_tag

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
        if has_tag(frontmatter.data):
            continue

        new_raw, changed = ensure_meta_tag(frontmatter.raw, DEFAULT_TAG_LITERAL)
        if not changed:
            continue

        skill_md_path.write_text(frontmatter.with_raw(new_raw), encoding="utf-8")
        updated += 1
        print(f"set meta.tag={DEFAULT_TAG_LITERAL} in {rel_path}")

    print(f"Checked {checked} SKILL.md files, updated {updated}.")


if __name__ == "__main__":
    main()
