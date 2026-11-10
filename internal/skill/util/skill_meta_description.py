"""Ensures a SKILL.md frontmatter's meta.description is set.

meta.description is an admin-only note for humans maintaining the skill
catalog. It is distinct from the top-level `description` field, which AI
agents read to decide when to invoke the skill and is left untouched here.

Thin wrapper around skill_meta_field.py's generic patcher, specialized to the
`description` field under `meta:`.
"""

from __future__ import annotations

from skill.util.skill_meta_field import ensure_meta_field, has_meta_field

DEFAULT_DESCRIPTION = "no description"


def has_description(data: dict) -> bool:
    return has_meta_field(data, "description")


def ensure_meta_description(
    raw: str, default_description: str = DEFAULT_DESCRIPTION
) -> tuple[str, bool]:
    """Return (patched_raw, changed) with a non-empty meta.description guaranteed."""
    return ensure_meta_field(raw, "description", default_description)
