"""Normalize AWS Knowledge MCP responses into data or typed errors.

The server reports ``is_error=False`` in every case (see
``memo/01-knowledge-mcp-server.md``); the actual outcome lives in the body, which
is always one JSON string in ``content[0].text``:

- ``{"errorMessage": "..."}``        bad arguments, off-allowlist URL, unknown
                                     filter name, unknown skill -> `ToolResponseError`
- ``{"content": {...}}``             success; `unwrap` returns the inner object
- no content block / blank text      seen on some ranges of long pages -> `EmptyResponseError`

Per-item outcomes of ``read_documentation`` (``status``/``error_code``/
``redirected_url``) are judged by the caller, since one bad URL must not sink
the rest of its batch.
"""

from __future__ import annotations

import json
from typing import Any

from awsdocs_core.client import content_text


class ToolResponseError(RuntimeError):
    """The tool rejected the call (maps to exit code 3)."""


class EmptyResponseError(RuntimeError):
    """The server returned no content at all (maps to exit code 1)."""


def unwrap(result) -> Any:
    """Return the ``content`` object of a successful call, or raise a typed error."""
    if result.is_error:
        raise ToolResponseError(content_text(result) or "tool reported an error")
    text = content_text(result)
    if not text.strip():
        raise EmptyResponseError("the server returned an empty response")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolResponseError(f"unexpected non-JSON response: {text[:500]}") from exc
    if isinstance(data, dict):
        if data.get("errorMessage"):
            raise ToolResponseError(str(data["errorMessage"]))
        if "content" in data:
            return data["content"]
    return data


def error_message_of(result) -> str | None:
    """The ``errorMessage`` of a raw result, if any (used by the `call` passthrough)."""
    try:
        data = json.loads(content_text(result))
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and data.get("errorMessage"):
        return str(data["errorMessage"])
    return None


def chunk_body(item: dict[str, Any]) -> str:
    """The page text of one read chunk, without the server-added preamble.

    A truncated chunk is prefixed with a ``Table of Contents:`` block (and a
    redirect ``Note:`` line when applicable) that isn't part of the page slice.
    The slice itself is exactly ``end_index - start_index`` chars, so it is the
    tail of ``content``. Used when stitching `fetch --all` continuation chunks.
    """
    content = item.get("content") or ""
    start = item.get("start_index") or 0
    end = item.get("end_index")
    if isinstance(end, int) and end > start and len(content) >= end - start:
        return content[len(content) - (end - start) :]
    return content
