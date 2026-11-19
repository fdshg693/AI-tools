"""Shared constants: exit codes, MCP endpoint/tool names, output-dir defaults."""

from __future__ import annotations

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1
EXIT_USAGE_ERROR = 2
EXIT_TOOL_ERROR = 3
EXIT_EMPTY_RESULT = 4

DEFAULT_ENDPOINT = "https://developerknowledge.googleapis.com/mcp"
API_KEY_ENV = "GDEVDOCS_API_KEY"
ENDPOINT_ENV = "GDEVDOCS_MCP_ENDPOINT"
OUTPUT_DIR_ENV = "GDEVDOCS_MCP_OUTPUT_DIR"
CONFIG_HOME_ENV = "GDEVDOCS_CONFIG_HOME"
DEFAULT_OUTPUT_DIR = "temp/gdevdocs_mcp"
DEFAULT_TIMEOUT = 60.0

SEARCH_TOOL = "search_documents"
FETCH_TOOL = "get_documents"
ANSWER_TOOL = "answer_query"
MAX_FETCH_NAMES = 20

# Only the per-minute search/get quotas are worth one short retry.
# AnswerQuery is 50/day, so a 429 there is not retried.
RATE_LIMIT_RETRY_TOOLS = frozenset({SEARCH_TOOL, FETCH_TOOL})
RATE_LIMIT_RETRY_SECONDS = 3.0
