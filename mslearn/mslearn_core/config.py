"""Shared constants: exit codes, MCP endpoint defaults, output-dir defaults."""

from __future__ import annotations

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1
EXIT_TOOL_ERROR = 3
EXIT_EMPTY_RESULT = 4

DEFAULT_ENDPOINT = "https://learn.microsoft.com/api/mcp"
ENDPOINT_ENV = "MSLEARN_MCP_ENDPOINT"
OUTPUT_DIR_ENV = "MSLEARN_MCP_OUTPUT_DIR"
DEFAULT_OUTPUT_DIR = "temp/mslearn_mcp"
DEFAULT_TIMEOUT = 30.0
