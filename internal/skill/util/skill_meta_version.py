"""Ensures a SKILL.md frontmatter's meta.version is set.

Thin wrapper around skill_meta_field.py's generic patcher, specialized to the
`version` field.
"""

from __future__ import annotations

from skill.util.skill_meta_field import ensure_meta_field, has_meta_field

DEFAULT_VERSION = "1.0.0"


def has_version(data: dict) -> bool:
    return has_meta_field(data, "version")


def ensure_meta_version(raw: str, default_version: str = DEFAULT_VERSION) -> tuple[str, bool]:
    """Return (patched_raw, changed) with a non-empty meta.version guaranteed."""
    return ensure_meta_field(raw, "version", default_version)
