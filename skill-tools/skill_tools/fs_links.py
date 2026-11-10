"""Treat Windows junctions like symlinks.

``Path.is_symlink()`` is False for a junction and ``os.walk(followlinks=False)``
descends into one, so every symlink guard in skill-tools goes through
``is_link_like`` instead. A same-named helper lives in the umbrella repository's
maintenance/scripts/links/fs.py; skill-tools keeps its own copy because it is
distributed on its own.
"""

from __future__ import annotations

import os
import stat

_MOUNT_POINT = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)


def is_link_like(path: str | os.PathLike[str]) -> bool:
    """True for a symlink or a junction (never follows the link itself)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return getattr(st, "st_reparse_tag", 0) == _MOUNT_POINT
