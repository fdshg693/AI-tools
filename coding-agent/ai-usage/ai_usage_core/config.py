"""Shared constants: log file locations, env var overrides."""

from __future__ import annotations

import os
from pathlib import Path

LOG_DIR_ENV = "AI_USAGE_LOG_DIR"
DEFAULT_LOG_DIR = "~/.ai-usage"
CLAUDE_CODE_LOG_FILENAME = "claude-code-rate-limits.jsonl"


def get_log_dir() -> Path:
    value = os.environ.get(LOG_DIR_ENV, "").strip()
    return Path(value or DEFAULT_LOG_DIR).expanduser()


def get_claude_code_log_path() -> Path:
    return get_log_dir() / CLAUDE_CODE_LOG_FILENAME
