"""Per-call folder writing: slugs, sequence numbers, the index.md summary.

One ``search`` / ``fetch`` / ``answer`` invocation writes a fresh folder:

    temp/gdevdocs_mcp/0001-<slug>/
        0001.md
        0002.md
        index.md

Stdout receives only the ``index.md`` path. Sequence allocation is serialized
with a file lock so two processes started together cannot pick the same prefix.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from gdevdocs_core.environment import get_output_dir

_SLUG_SEPARATOR = re.compile(r"[^\w]+", re.UNICODE)
_SEQUENCE_PREFIX = re.compile(r"^(\d{4})")
_LOCK_NAME = ".sequence.lock"
_LOCK_WAIT_SECONDS = 15.0
_LOCK_POLL_SECONDS = 0.05


def slugify(text: str | None, *, max_length: int = 50) -> str:
    lowered = (text or "").strip().lower()
    slug = _SLUG_SEPARATOR.sub("-", lowered).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or "item"


def _link_title(title: str) -> str:
    cleaned = title.replace("[", "(").replace("]", ")").replace("\n", " ").strip()
    return cleaned or "untitled"


def _next_prefixed_sequence(directory: Path) -> int:
    if not directory.exists():
        return 1
    highest = 0
    for entry in directory.iterdir():
        match = _SEQUENCE_PREFIX.match(entry.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


@contextmanager
def _exclusive_file_lock(lock_path: Path) -> Iterator[None]:
    """Cross-process exclusive lock; released automatically if the holder dies."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+b")
    try:
        fh.seek(0, os.SEEK_END)
        if fh.tell() == 0:
            fh.write(b"\0")
            fh.flush()
        deadline = time.monotonic() + _LOCK_WAIT_SECONDS
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out waiting for sequence lock at {lock_path}")
                    time.sleep(_LOCK_POLL_SECONDS)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out waiting for sequence lock at {lock_path}")
                    time.sleep(_LOCK_POLL_SECONDS)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def _claim_next_folder(root: Path, slug: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    with _exclusive_file_lock(root / _LOCK_NAME):
        sequence = _next_prefixed_sequence(root)
        folder = root / f"{sequence:04d}-{slug}"
        folder.mkdir(parents=True)
        return folder


def write_query_results(label: str, items: Sequence[tuple[str, str]]) -> Path:
    """Write one call's ``(title, content)`` items. Return the ``index.md`` path."""
    folder = _claim_next_folder(get_output_dir(), slugify(label))
    lines = [f"# {label}", "", "## Results"]
    for position, (title, content) in enumerate(items, start=1):
        filename = f"{position:04d}.md"
        (folder / filename).write_text(content, encoding="utf-8")
        lines.append(f"- [{_link_title(title)}]({filename}) ({len(content)} chars)")
    lines.append("")
    (folder / "index.md").write_text("\n".join(lines), encoding="utf-8")
    return folder / "index.md"


def print_index_path(index_path: Path) -> None:
    """Print only the index.md path — never per-result paths or content."""
    print(index_path)
