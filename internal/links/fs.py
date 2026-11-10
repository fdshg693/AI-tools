"""Filesystem helpers that treat Windows junctions like symlinks.

``Path.is_symlink()`` / ``os.path.islink()`` return False for a junction, and
``os.walk(followlinks=False)`` / ``Path.rglob`` descend into one. Every scanner
in tools/internal goes through ``is_link_like`` / ``walk_no_links`` instead, so a
junction created by ``just links-sync`` is never counted twice or walked into.
See docs/repo-wide/repo-layout.md.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

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


def walk_no_links(
    root: str | os.PathLike[str], excluded_names: Iterable[str] = ()
) -> Iterator[tuple[str, list[str], list[str]]]:
    """``os.walk`` that prunes link-like directories and ``excluded_names``."""
    excluded = set(excluded_names)
    for dir_path, dir_names, file_names in os.walk(root):
        dir_names[:] = [
            name
            for name in dir_names
            if name not in excluded and not is_link_like(os.path.join(dir_path, name))
        ]
        yield dir_path, dir_names, file_names


def link_target(path: str | os.PathLike[str]) -> Path | None:
    """Absolute target of a link-like path, without the ``\\\\?\\`` prefix."""
    if not is_link_like(path):
        return None
    try:
        raw = os.readlink(path)
    except OSError:
        return None
    for prefix in ("\\\\?\\", "\\??\\"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    target = Path(raw)
    if not target.is_absolute():
        target = Path(path).parent / target
    return Path(os.path.normpath(target))


def remove_link(path: str | os.PathLike[str]) -> None:
    """Remove only the link itself. Refuses anything that is not link-like.

    Never use shutil.rmtree / ``rm -rf`` / ``Remove-Item -Recurse`` on a
    junction: they can delete the target's contents.
    """
    if not is_link_like(path):
        raise OSError(f"refusing to remove a non-link path: {path}")
    if sys.platform == "win32":
        os.rmdir(path)  # removes the junction / directory symlink, not the target
    else:
        os.unlink(path)


def create_junction(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import subprocess

        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not is_link_like(link):
            raise OSError(f"mklink /J failed for {link}: {(result.stdout + result.stderr).strip()}")
    else:
        os.symlink(target, link, target_is_directory=True)


def same_path(a: str | os.PathLike[str], b: str | os.PathLike[str]) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def is_within(child: str | os.PathLike[str], parent: str | os.PathLike[str]) -> bool:
    """True when ``child`` equals ``parent`` or lies below it (lexically)."""
    c = os.path.normcase(os.path.abspath(child))
    p = os.path.normcase(os.path.abspath(parent))
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)
