"""Per-query folder writing: slugs, sequence numbers, the index.md summary.

Nothing here knows what a "match" is -- that shaping happens in `rendering.py`.
This module only turns a list of (category, title, content) triples into one
folder per query call:

    temp/grepapp_mcp/0001-<query-slug>/
        0001.md            <- matched file
        0002.md            <- matched file
        index.md           <- filename + title per item, only path printed to stdout

The folder itself is prefixed with a sequence number (scanned across the output
root) so re-running the same query never overwrites a previous run's results --
each run is a fresh, separately timestamped snapshot.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path

from grepapp_core.config import DEFAULT_OUTPUT_DIR, OUTPUT_DIR_ENV

_SLUG_SEPARATOR = re.compile(r"[^\w]+", re.UNICODE)
_SEQUENCE_PREFIX = re.compile(r"^(\d{4})")


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


def write_query_results(label: str, items: Sequence[tuple[str, str, str]]) -> Path:
    """Write one query's results into a fresh numbered folder; return the index.md path.

    `items` are (category, title, content) triples from `rendering.py`. `category`
    is always `""` for grep.app (no qa/-style split), so every item is written at
    the folder root. Files are named by a plain running sequence (`0001.md`,
    `0002.md`, ...) -- the title lives in `index.md`, not the filename, so it no
    longer needs to carry a slug.

    Each `index.md` line carries its file's char count (`len(content)`). A whole-run
    total wouldn't mean anything actionable -- what matters is picking, per file, which
    ones are worth a raw Read and which are large enough to route through `aim --parallel`
    instead -- so no aggregate is computed here.
    """
    root = get_output_dir()
    root.mkdir(parents=True, exist_ok=True)
    sequence = _next_prefixed_sequence(root)
    folder = root / f"{sequence:04d}-{slugify(label)}"
    folder.mkdir(parents=True)

    docs_lines: list[str] = []
    qa_lines: list[str] = []
    for position, (category, title, content) in enumerate(items, start=1):
        filename = f"{position:04d}.md"
        char_count = len(content)
        if category == "qa":
            (folder / "qa").mkdir(exist_ok=True)
            file_path = folder / "qa" / filename
            rel_path = f"qa/{filename}"
            qa_lines.append(f"- [{title}]({rel_path}) ({char_count} chars)")
        else:
            file_path = folder / filename
            rel_path = filename
            docs_lines.append(f"- [{title}]({rel_path}) ({char_count} chars)")
        file_path.write_text(content, encoding="utf-8")

    index_lines = [f"# {label}", ""]
    if docs_lines:
        index_lines += ["## Docs", *docs_lines, ""]
    if qa_lines:
        index_lines += ["## Q&A", *qa_lines, ""]
    (folder / "index.md").write_text("\n".join(index_lines).rstrip() + "\n", encoding="utf-8")

    return folder / "index.md"


def print_index_path(index_path: Path) -> None:
    """Print only the index.md path -- never per-result paths or content."""
    print(index_path)
