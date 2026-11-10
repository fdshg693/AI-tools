"""Pure helper for bumping the trailing numeric segment of a version string.

Any pre-release/build suffix stuck to the last segment (``1.2.3-beta``,
``1.2.3+build4``) is dropped rather than preserved: the bumped result is
always a clean dot-separated integer version (e.g. ``1.2.4``).
"""

from __future__ import annotations

import re

_LAST_SEGMENT_RE = re.compile(r"^(\d+)")


def bump_last_numeric_segment(version: str) -> str | None:
    """Return ``version`` with its last dot-segment's leading integer +1.

    Returns ``None`` if the last segment has no leading digits to bump.
    """
    segments = version.strip().split(".")
    if not segments:
        return None

    match = _LAST_SEGMENT_RE.match(segments[-1])
    if match is None:
        return None

    segments[-1] = str(int(match.group(1)) + 1)
    return ".".join(segments)
