"""Optional ``.env`` loading and runtime settings (output dir, size cap)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from pyinspect_core.config import (
    DEFAULT_MAX_BYTES,
    DEFAULT_OUTPUT_DIR,
    MAX_BYTES_ENV,
    OUTPUT_DIR_ENV,
    PACKAGE_NAME,
    USER_AGENT_PREFIX,
)

PYINSPECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PYINSPECT_ROOT / ".env"


def load_environment() -> str | None:
    """Load ``tools/pyinspect/.env`` if present. Return that path, or None."""
    load_dotenv(ENV_PATH, override=False)
    if ENV_PATH.is_file():
        return str(ENV_PATH)
    return None


def get_output_dir() -> Path:
    """Cache root. Relative values (including the default) resolve against cwd."""
    value = os.environ.get(OUTPUT_DIR_ENV, "").strip()
    return Path(value or DEFAULT_OUTPUT_DIR)


def get_max_bytes() -> int:
    raw = os.environ.get(MAX_BYTES_ENV, "").strip()
    if not raw:
        return DEFAULT_MAX_BYTES
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{MAX_BYTES_ENV} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{MAX_BYTES_ENV} must be positive, got {value}")
    return value


def user_agent() -> str:
    try:
        from importlib.metadata import version

        ver = version(PACKAGE_NAME)
    except Exception:
        ver = "0.1.0"
    return f"{USER_AGENT_PREFIX}/{ver}"
