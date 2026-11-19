"""fastmcp.Client wiring: connect to the Microsoft Learn MCP server and call/list its tools.

Kept free of argparse -- callers pass plain values, not an ``argparse.Namespace``,
so this module stays reusable from anything (CLI, tests, a future non-CLI caller).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from mslearn_core.config import DEFAULT_ENDPOINT, ENDPOINT_ENV


def build_endpoint(base: str, max_token_budget: int | None) -> str:
    """Append `?maxTokenBudget=N` (search-only, per the server's own docs) if set."""
    if max_token_budget is None:
        return base
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}maxTokenBudget={max_token_budget}"


def resolve_endpoint(endpoint_override: str | None, max_token_budget: int | None = None) -> str:
    base = endpoint_override or os.environ.get(ENDPOINT_ENV, "").strip() or DEFAULT_ENDPOINT
    return build_endpoint(base, max_token_budget)


async def _call_tool_async(
    endpoint: str, timeout: float, tool_name: str, arguments: dict[str, Any]
):
    from fastmcp import Client

    client = Client(endpoint, timeout=timeout)
    async with client:
        return await client.call_tool(tool_name, arguments, raise_on_error=False)


async def _list_tools_async(endpoint: str, timeout: float):
    from fastmcp import Client

    client = Client(endpoint, timeout=timeout)
    async with client:
        return await client.list_tools()


def call_tool(endpoint: str, timeout: float, tool_name: str, arguments: dict[str, Any]):
    return asyncio.run(_call_tool_async(endpoint, timeout, tool_name, arguments))


def list_tools(endpoint: str, timeout: float):
    return asyncio.run(_list_tools_async(endpoint, timeout))


def content_text(result) -> str:
    """Concatenate any TextContent blocks in a CallToolResult (fetch has no structured_content)."""
    return "\n".join(block.text for block in result.content if hasattr(block, "text"))
