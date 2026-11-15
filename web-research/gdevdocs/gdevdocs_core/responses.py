"""Normalize a Developer Knowledge MCP ``CallToolResult`` into a dict or a typed error."""

from __future__ import annotations

import json
from typing import Any


class ToolResponseError(RuntimeError):
    """The tool rejected the call (maps to exit code 3)."""


class EmptyResponseError(RuntimeError):
    """The server returned no content at all (maps to exit code 1)."""


def content_text(result) -> str:
    blocks = getattr(result, "content", None) or []
    return "\n".join(block.text for block in blocks if hasattr(block, "text"))


def structured_dict(result) -> dict[str, Any] | None:
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if hasattr(structured, "model_dump"):
        structured = structured.model_dump()
    if isinstance(structured, dict) and structured:
        return structured
    return None


def as_payload(result) -> Any:
    """Return the tool payload. ``is_error`` becomes ``ToolResponseError``."""
    if getattr(result, "is_error", False):
        raise ToolResponseError(content_text(result) or "tool reported an error")
    structured = structured_dict(result)
    if structured is not None:
        return structured
    text = content_text(result)
    if not text.strip():
        raise EmptyResponseError("the server returned an empty response")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolResponseError(f"unexpected non-JSON response: {text[:500]}") from exc


def payload_json(result) -> str:
    """Raw JSON for ``call``. Prefer structured content, else the text block."""
    structured = structured_dict(result)
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False, indent=2)
    text = content_text(result)
    if text:
        return text
    return json.dumps({"is_error": bool(getattr(result, "is_error", False))}, ensure_ascii=False)
