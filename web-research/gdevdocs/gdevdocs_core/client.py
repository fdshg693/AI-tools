"""fastmcp.Client wiring for the Developer Knowledge MCP server.

The API key is sent as the ``X-Goog-Api-Key`` header and never as a query
parameter. ``search_documents`` and ``get_documents`` retry once after 3 seconds
on HTTP 429. ``answer_query`` does not: its default quota is 50 calls per day.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from gdevdocs_core.config import RATE_LIMIT_RETRY_SECONDS, RATE_LIMIT_RETRY_TOOLS
from gdevdocs_core.responses import content_text

T = TypeVar("T")

_RATE_LIMIT_JSONRPC_CODE = -32004
_RATE_LIMIT_MARKERS = ("too many requests", "resource exhausted", "resource_exhausted")


class RateLimitError(RuntimeError):
    """The server refused the request with HTTP 429 (after the allowed retry, if any)."""


def retries_rate_limit(tool_name: str) -> bool:
    return tool_name in RATE_LIMIT_RETRY_TOOLS


def _iter_exception_chain(exc: BaseException):
    seen: set[int] = set()
    stack = [exc]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        stack.extend(getattr(current, "exceptions", ()) or ())
        stack.append(current.__cause__)
        stack.append(current.__context__)


def is_rate_limit_error(exc: BaseException) -> bool:
    """True if `exc` (or anything it wraps) is an HTTP 429 or a quota-style tool error."""
    if isinstance(exc, RateLimitError):
        return True
    for current in _iter_exception_chain(exc):
        response = getattr(current, "response", None)
        if getattr(response, "status_code", None) == 429:
            return True
        error = getattr(current, "error", None)
        if getattr(error, "code", None) == _RATE_LIMIT_JSONRPC_CODE:
            return True
        text = str(current).lower()
        if "429" in text or any(marker in text for marker in _RATE_LIMIT_MARKERS):
            return True
    return False


def result_is_rate_limited(result) -> bool:
    if not getattr(result, "is_error", False):
        return False
    text = content_text(result).lower()
    return "429" in text or any(marker in text for marker in _RATE_LIMIT_MARKERS)


def _redact(text: str, api_key: str) -> str:
    if api_key and api_key in text:
        return text.replace(api_key, "***")
    return text


def public_error(exc: BaseException, api_key: str) -> str:
    return _redact(f"{type(exc).__name__}: {exc}", api_key)


async def _with_rate_limit_retry(factory: Callable[[], Awaitable[T]]) -> T:
    try:
        return await factory()
    except Exception as exc:
        if not is_rate_limit_error(exc):
            raise
    await asyncio.sleep(RATE_LIMIT_RETRY_SECONDS)
    try:
        return await factory()
    except Exception as exc:
        if is_rate_limit_error(exc):
            raise RateLimitError(
                "Rate limited by the Developer Knowledge MCP server (HTTP 429); "
                "wait and retry. answer_query is not retried — use search instead."
            ) from exc
        raise


def _connect(endpoint: str, api_key: str, timeout: float):
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    transport = StreamableHttpTransport(endpoint, headers={"X-Goog-Api-Key": api_key})
    return Client(transport, timeout=timeout)


async def _run_async(
    endpoint: str,
    api_key: str,
    timeout: float,
    body: Callable[[Any], Awaitable[T]],
    *,
    retry_rate_limit: bool,
) -> T:
    async def attempt() -> T:
        client = _connect(endpoint, api_key, timeout)
        async with client:
            return await body(client)

    if not retry_rate_limit:
        try:
            return await attempt()
        except Exception as exc:
            if is_rate_limit_error(exc):
                raise RateLimitError(
                    "Rate limited by the Developer Knowledge MCP server (HTTP 429). "
                    "answer_query is not retried — use search instead."
                ) from exc
            raise
    return await _with_rate_limit_retry(attempt)


def run(
    endpoint: str,
    api_key: str,
    timeout: float,
    body: Callable[[Any], Awaitable[T]],
    *,
    retry_rate_limit: bool,
) -> T:
    return asyncio.run(
        _run_async(endpoint, api_key, timeout, body, retry_rate_limit=retry_rate_limit)
    )


def call_tool(
    endpoint: str,
    api_key: str,
    timeout: float,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    retry_rate_limit: bool,
):
    async def body(mcp):
        result = await mcp.call_tool(tool_name, arguments, raise_on_error=False)
        if result_is_rate_limited(result):
            raise RateLimitError(content_text(result) or "HTTP 429")
        return result

    return run(endpoint, api_key, timeout, body, retry_rate_limit=retry_rate_limit)


def list_tools(endpoint: str, api_key: str, timeout: float):
    async def body(mcp):
        return await mcp.list_tools()

    return run(endpoint, api_key, timeout, body, retry_rate_limit=True)
