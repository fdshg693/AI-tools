"""Shared constants: exit codes, MCP endpoint/tool names, output-dir defaults."""

from __future__ import annotations

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1
EXIT_TOOL_ERROR = 3
EXIT_EMPTY_RESULT = 4

DEFAULT_ENDPOINT = "https://knowledge-mcp.global.api.aws"
ENDPOINT_ENV = "AWSDOCS_MCP_ENDPOINT"
OUTPUT_DIR_ENV = "AWSDOCS_MCP_OUTPUT_DIR"
DEFAULT_OUTPUT_DIR = "temp/awsdocs_mcp"
DEFAULT_TIMEOUT = 60.0

# Every tool the Knowledge MCP server advertises carries this prefix. Kept in one
# place so a server-side rename only touches this file (`tools` / `call` remain
# the escape hatch for tools this CLI doesn't wrap yet).
TOOL_PREFIX = "aws___"
SEARCH_TOOL = f"{TOOL_PREFIX}search_documentation"
READ_TOOL = f"{TOOL_PREFIX}read_documentation"
LIST_REGIONS_TOOL = f"{TOOL_PREFIX}list_regions"
AVAILABILITY_TOOL = f"{TOOL_PREFIX}get_regional_availability"
SKILL_TOOL = f"{TOOL_PREFIX}retrieve_skill"

# The server silently ignores unknown topics (falls back to `general`), so the CLI
# validates against this list instead.
SEARCH_TOPICS = (
    "reference_documentation",
    "current_awareness",
    "troubleshooting",
    "amplify_docs",
    "cdk_docs",
    "cdk_constructs",
    "cloudformation",
    "strands_docs",
    "agent_skills",
    "general",
)
MAX_TOPICS = 3
DEFAULT_SEARCH_LIMIT = 10

READ_BATCH_SIZE = 5  # server rejects more than 5 requests per read call
MAX_READ_ROUNDS = 100  # safety cap for `fetch --all` continuation reads

AVAILABILITY_TYPES = ("product", "api", "cfn")
MAX_AVAILABILITY_REGIONS = 10

RATE_LIMIT_RETRY_SECONDS = 3.0
