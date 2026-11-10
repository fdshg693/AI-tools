"""Turn one raw `searchGitHub` result block into a (category, title, markdown)
triple for `output.write_query_results`.

`searchGitHub` has no `structured_content`/`data` -- every hit comes back as a
separate TextContent block in `result.content` (one block per matched file, up
to 10, no paging). This module owns turning one such block into the on-disk
shape; `output.py` only knows how to write a (category, title, content) triple
into a query folder, it has no idea what a grep.app match looks like.
"""

from __future__ import annotations

import re
from typing import Any

_REPO_LINE = re.compile(r"^Repository: (.+)$", re.MULTILINE)
_PATH_LINE = re.compile(r"^Path: (.+)$", re.MULTILINE)


def is_empty_response(content: list[Any]) -> bool:
    """True when `searchGitHub` found nothing.

    Detected structurally (a single block whose text doesn't start with
    "Repository: ") rather than by matching the server's exact "No results
    found for your query." wording -- that wording isn't part of the tool's
    contract and a server-side copy change would silently break a literal
    match.
    """
    if len(content) != 1:
        return False
    text = getattr(content[0], "text", "")
    return not text.startswith("Repository: ")


def render_match_item(position: int, block_text: str) -> tuple[str, str, str]:
    repo_match = _REPO_LINE.search(block_text)
    path_match = _PATH_LINE.search(block_text)
    if repo_match and path_match:
        title = f"{repo_match.group(1)} — {path_match.group(1)}"
    else:
        # Falls back instead of raising if the server ever changes its header
        # format -- a match is still worth writing out even unlabeled.
        title = f"result-{position}"
    content = f"# {title}\n\n{block_text}"
    return "", title, content
