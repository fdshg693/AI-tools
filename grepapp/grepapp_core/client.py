"""fastmcp.Client wiring: connect to the grep.app MCP server and call/list its tools.

Kept free of argparse -- callers pass plain values, not an ``argparse.Namespace``,
so this module stays reusable from anything (CLI, tests, a future non-CLI caller).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from grepapp_core.config import DEFAULT_ENDPOINT, ENDPOINT_ENV


def resolve_endpoint(endpoint_override: str | None) -> str:
    return endpoint_override or os.environ.get(ENDPOINT_ENV, "").strip() or DEFAULT_ENDPOINT


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
    """Concatenate any TextContent blocks in a CallToolResult."""
    return "\n".join(block.text for block in result.content if hasattr(block, "text"))
