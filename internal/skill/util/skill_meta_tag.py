"""Ensures a SKILL.md frontmatter's meta.tag is set.

meta.tag is an array of topic tags drawn from the allowed values registered
in skill-tags.yaml (repo root). Unlike version/description, no value needs to
be guessed here: an empty array is itself a legitimate default, so this only
backfills a missing field rather than classifying anything.

Thin wrapper around skill_meta_field.py's generic patcher, specialized to the
`tag` field under `meta:`.
"""

from __future__ import annotations

from skill.util.skill_meta_field import ensure_meta_field_literal, has_meta_field

DEFAULT_TAG_LITERAL = "[]"


def has_tag(data: dict) -> bool:
    return has_meta_field(data, "tag")


def ensure_meta_tag(raw: str, default_tag_literal: str = DEFAULT_TAG_LITERAL) -> tuple[str, bool]:
    """Return (patched_raw, changed) with meta.tag guaranteed to exist."""
    return ensure_meta_field_literal(raw, "tag", default_tag_literal)
