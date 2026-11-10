"""Shared constants: exit codes, cache defaults, timeouts."""

from __future__ import annotations

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_METADATA_ONLY = 4
EXIT_IMPORT_FAILED = 5

PACKAGE_NAME = "pyinspect-cli"
CLI_NAME = "pyinspect"
USER_AGENT_PREFIX = "pyinspect"

DEFAULT_OUTPUT_DIR = "temp/py-inspect"
OUTPUT_DIR_ENV = "PYINSPECT_OUTPUT_DIR"
MAX_BYTES_ENV = "PYINSPECT_MAX_BYTES"
DEFAULT_MAX_BYTES = 50_000_000

DEFAULT_HTTP_TIMEOUT = 30.0

# Isolated `--import` runs arbitrary package code in an ephemeral venv.
# A hung import should not keep the CLI process alive.
IMPORT_TIMEOUT_SECONDS = 60

TREE_ENTRY_LIMIT = 2000
RECOMMENDED_PATH_LIMIT = 8

PYPI_JSON_BASE = "https://pypi.org/pypi"
