"""Shared constants: exit codes, MCP endpoint defaults, output-dir defaults."""

from __future__ import annotations

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1
EXIT_TOOL_ERROR = 3
EXIT_EMPTY_RESULT = 4

DEFAULT_ENDPOINT = "https://mcp.grep.app"
ENDPOINT_ENV = "GREPAPP_MCP_ENDPOINT"
OUTPUT_DIR_ENV = "GREPAPP_MCP_OUTPUT_DIR"
DEFAULT_OUTPUT_DIR = "temp/grepapp_mcp"
# Higher than mslearn's 30s default: a cold-start request measured a 504
# Gateway Timeout at 20s but succeeded at 40s (see memo/00-findings.md).
DEFAULT_TIMEOUT = 45.0
