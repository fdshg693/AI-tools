"""Per-query folder writing: slugs, sequence numbers, the index.md summary.

Nothing here knows what a "search result" or "fetched page" is -- that shaping
happens in `rendering.py`. This module only turns a list of (category, title,
content) triples into one folder per search/fetch/skill call:

    temp/awsdocs_mcp/0001-<query-slug>/
        0001.md             <- documentation result
        blog/0002.md        <- AWS Blog result
        whats-new/0003.md   <- What's New announcement
        repost/0004.md      <- re:Post Knowledge Center article
        skills/0005.md      <- AWS Agent Skill entry (no URL)
        index.md            <- filename + title + char count per item, grouped
                               by category; only this path is printed to stdout

The folder itself is prefixed with a sequence number (scanned across the output
root) so re-running the same query never overwrites a previous run's results --
each run is a fresh, separately timestamped snapshot. Allocation of that number
is serialized with a file lock so two `awsdocs` processes started in parallel
(e.g. `cmd1 & cmd2`) cannot both pick the same `NNNN`.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from awsdocs_core.config import DEFAULT_OUTPUT_DIR, OUTPUT_DIR_ENV

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


def get_output_dir() -> Path:
    value = os.environ.get(OUTPUT_DIR_ENV, "").strip()
    return Path(value or DEFAULT_OUTPUT_DIR)


def _next_prefixed_sequence(directory: Path) -> int:
    """Highest `NNNN` prefix among entries directly inside `directory`, plus one."""
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
    """Pick the next `NNNN-<slug>/` under `root` without racing a sibling process."""
    root.mkdir(parents=True, exist_ok=True)
    with _exclusive_file_lock(root / _LOCK_NAME):
        sequence = _next_prefixed_sequence(root)
        folder = root / f"{sequence:04d}-{slug}"
        folder.mkdir(parents=True)
        return folder


# Category -> index.md heading, in display order. "" is the folder root.
CATEGORY_HEADINGS = {
    "": "Docs",
    "blog": "Blog",
    "whats-new": "What's New",
    "repost": "re:Post",
    "skills": "Skills",
}


def write_query_results(
    label: str,
    items: Sequence[tuple[str, str, str]],
    *,
    warnings: Sequence[str] = (),
    errors: Sequence[str] = (),
) -> Path:
    """Write one call's results into a fresh numbered folder; return the index.md path.

    `items` are (category, title, content) triples from `rendering.py`. `category`
    `""` writes to the folder root, any other key of `CATEGORY_HEADINGS` writes
    under a subfolder of that name. Files are named by a plain running sequence
    (`0001.md`, `0002.md`, ...) across all categories, so `rank_order` survives in
    the filename -- the title lives in `index.md`, not the filename.

    Each `index.md` line carries its file's char count (`len(content)`), so a caller
    can decide per file whether to Read it raw or route it through `aim --parallel`.
    `warnings` / `errors` (e.g. redirected or failed URLs in a `fetch` batch) are
    listed under their own headings so they aren't lost when only the path is printed.
    """
    folder = _claim_next_folder(get_output_dir(), slugify(label))

    lines_by_category: dict[str, list[str]] = {key: [] for key in CATEGORY_HEADINGS}
    for position, (category, title, content) in enumerate(items, start=1):
        if category not in CATEGORY_HEADINGS:
            raise ValueError(f"unknown result category: {category!r}")
        filename = f"{position:04d}.md"
        if category:
            (folder / category).mkdir(exist_ok=True)
            rel_path = f"{category}/{filename}"
        else:
            rel_path = filename
        (folder / rel_path).write_text(content, encoding="utf-8")
        lines_by_category[category].append(f"- [{title}]({rel_path}) ({len(content)} chars)")

    index_lines = [f"# {label}", ""]
    for category, heading in CATEGORY_HEADINGS.items():
        if lines_by_category[category]:
            index_lines += [f"## {heading}", *lines_by_category[category], ""]
    if warnings:
        index_lines += ["## Warnings", *(f"- {w}" for w in warnings), ""]
    if errors:
        index_lines += ["## Errors", *(f"- {e}" for e in errors), ""]
    (folder / "index.md").write_text("\n".join(index_lines).rstrip() + "\n", encoding="utf-8")

    return folder / "index.md"


def print_index_path(index_path: Path) -> None:
    """Print only the index.md path -- never per-result paths or content."""
    print(index_path)
