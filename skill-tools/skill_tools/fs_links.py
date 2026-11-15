"""Treat Windows junctions like symlinks, and create/remove directory links.

``Path.is_symlink()`` is False for a junction and ``os.walk(followlinks=False)``
descends into one, so every symlink guard in skill-tools goes through
``is_link_like`` instead. Same-named helpers live in the umbrella repository's
maintenance/scripts/links/fs.py; skill-tools keeps its own copy because it is
distributed on its own.

Link installs use ``create_dir_link``: a junction on Windows (no administrator
rights or developer mode needed), a directory symlink elsewhere. Both always
point at an absolute target.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

_MOUNT_POINT = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
_EXTENDED_PREFIXES = ("\\\\?\\", "\\??\\")


def is_link_like(path: str | os.PathLike[str]) -> bool:
    """True for a symlink or a junction (never follows the link itself)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return getattr(st, "st_reparse_tag", 0) == _MOUNT_POINT


def link_target(path: str | os.PathLike[str]) -> Path | None:
    """Absolute target of a link-like path, or None for anything else.

    Works for a broken link too. Strips the extended-length prefix a junction's
    ``os.readlink`` returns, so the result compares with ordinary paths.
    """
    if not is_link_like(path):
        return None
    try:
        raw = os.readlink(path)
    except OSError:
        return None
    for prefix in _EXTENDED_PREFIXES:
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    target = Path(raw)
    if not target.is_absolute():
        target = Path(path).parent / target
    return Path(os.path.normpath(target))


def same_path(a: str | os.PathLike[str], b: str | os.PathLike[str]) -> bool:
    """Lexical path equality (absolute, normalized, case-insensitive on Windows)."""
    return os.path.normcase(os.path.normpath(os.path.abspath(a))) == os.path.normcase(
        os.path.normpath(os.path.abspath(b))
    )


def same_link_target(path: str | os.PathLike[str], expected: str | os.PathLike[str]) -> bool:
    """True when ``path`` is a link whose target is ``expected``."""
    target = link_target(path)
    return target is not None and same_path(target, expected)


def remove_link(path: str | os.PathLike[str]) -> None:
    """Remove only the link itself; refuse anything that is not link-like.

    Never use ``shutil.rmtree`` for this: removing the link is the only
    intended effect, whatever the target holds.
    """
    if not is_link_like(path):
        raise OSError(f"refusing to remove a non-link path: {path}")
    if sys.platform == "win32":
        os.rmdir(path)  # removes the junction / directory symlink, not the target
    else:
        os.unlink(path)


def create_dir_link(link: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
    """Create ``link`` pointing at the existing real directory ``target``.

    Windows uses ``_winapi.CreateJunction`` rather than ``cmd /c mklink /J``:
    cmd re-parses the arguments, so ``&`` breaks the command, ``^`` silently
    creates a link at a different path, and ``%VAR%`` is expanded. ``link`` must
    not exist yet. The created link is checked with ``link_target`` before
    returning, and removed again if it points anywhere else.
    """
    link_path = Path(link)
    target_path = Path(os.path.normpath(os.path.abspath(target)))
    if is_link_like(target_path) or not target_path.is_dir():
        raise OSError(f"link target must be an existing real directory: {target_path}")
    if os.path.lexists(link_path):
        raise FileExistsError(f"link path already exists: {link_path}")
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target_path), str(link_path))
    else:
        os.symlink(target_path, link_path, target_is_directory=True)
    if not same_link_target(link_path, target_path):
        actual = link_target(link_path)
        if is_link_like(link_path):
            remove_link(link_path)
        raise OSError(f"created link {link_path} points at {actual}, expected {target_path}")
