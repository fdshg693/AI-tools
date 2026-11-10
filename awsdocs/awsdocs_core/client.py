"""fastmcp.Client wiring: connect to the AWS Knowledge MCP server and call/list its tools.

Kept free of argparse -- callers pass plain values, not an ``argparse.Namespace``,
so this module stays reusable from anything (CLI, tests, a future non-CLI caller).

Unlike the Microsoft Learn server, one CLI run may need several tool calls
(`fetch` splits URLs into batches of 5 and `--all` keeps reading while the page is
truncated). Every connection pays an ``initialize`` handshake against a
rate-limited endpoint, so those calls share one `Session` instead of reconnecting
per call. Rate limiting (HTTP 429 / JSON-RPC ``-32004``) is retried once after a
short wait and then surfaced as `RateLimitError`.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from awsdocs_core.config import DEFAULT_ENDPOINT, ENDPOINT_ENV, RATE_LIMIT_RETRY_SECONDS

T = TypeVar("T")

_RATE_LIMIT_JSONRPC_CODE = -32004
_RATE_LIMIT_MARKER = "too many requests"


class RateLimitError(RuntimeError):
    """The server refused the request with HTTP 429 / JSON-RPC -32004 (after one retry)."""


def resolve_endpoint(endpoint_override: str | None) -> str:
    return endpoint_override or os.environ.get(ENDPOINT_ENV, "").strip() or DEFAULT_ENDPOINT


def _iter_exception_chain(exc: BaseException):
    seen: set[int] = set()
    stack = [exc]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        stack.extend(getattr(current, "exceptions", ()) or ())  # ExceptionGroup
        stack.append(current.__cause__)
        stack.append(current.__context__)


def is_rate_limit_error(exc: BaseException) -> bool:
    """True if `exc` (or anything it wraps) is an HTTP 429 or JSON-RPC -32004."""
    for current in _iter_exception_chain(exc):
        response = getattr(current, "response", None)
        if getattr(response, "status_code", None) == 429:
            return True
        error = getattr(current, "error", None)
        if getattr(error, "code", None) == _RATE_LIMIT_JSONRPC_CODE:
            return True
        if _RATE_LIMIT_MARKER in str(current).lower():
            return True
    return False


async def _with_rate_limit_retry(factory: Callable[[], Awaitable[T]]) -> T:
    try:
        return await factory()
    except RateLimitError:
        raise  # an inner call already retried; don't replay the whole session
    except Exception as exc:
        if not is_rate_limit_error(exc):
            raise
    await asyncio.sleep(RATE_LIMIT_RETRY_SECONDS)
    try:
        return await factory()
    except Exception as exc:
        if is_rate_limit_error(exc):
            raise RateLimitError(
                "Rate limited by the AWS Knowledge MCP server (HTTP 429 / -32004); "
                "wait a while and retry."
            ) from exc
        raise


class Session:
    """One connected fastmcp.Client, reused for every tool call in a CLI run."""

    def __init__(self, client) -> None:
        self._client = client

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]):
        return await _with_rate_limit_retry(
            lambda: self._client.call_tool(tool_name, arguments, raise_on_error=False)
        )

    async def list_tools(self):
        return await _with_rate_limit_retry(self._client.list_tools)


async def _run_async(endpoint: str, timeout: float, body: Callable[[Session], Awaitable[T]]) -> T:
    from fastmcp import Client

    async def attempt() -> T:
        client = Client(endpoint, timeout=timeout)
        async with client:
            return await body(Session(client))

    return await _with_rate_limit_retry(attempt)


def run(endpoint: str, timeout: float, body: Callable[[Session], Awaitable[T]]) -> T:
    """Open one session, run `body(session)` and close it (handshake retried on 429)."""
    return asyncio.run(_run_async(endpoint, timeout, body))


def call_tool(endpoint: str, timeout: float, tool_name: str, arguments: dict[str, Any]):
    return run(endpoint, timeout, lambda session: session.call_tool(tool_name, arguments))


def list_tools(endpoint: str, timeout: float):
    return run(endpoint, timeout, lambda session: session.list_tools())


def content_text(result) -> str:
    """Concatenate any TextContent blocks in a CallToolResult (the server puts one JSON string there)."""
    return "\n".join(block.text for block in result.content if hasattr(block, "text"))
