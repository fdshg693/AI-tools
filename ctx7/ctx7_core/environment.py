"""Environment & credentials: ``.env`` loading and the Context7 API key.

Loads ``tools/ctx7/.env`` only (no cwd or parent search). The API key here is
never required. Context7's REST API answers unauthenticated requests too --
this was confirmed by hand against both endpoints this package calls (see
README "認証") -- so a missing/blank key is a normal, supported state, not an
error. Everything that reads the process environment lives in this one file.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

API_KEY_ENV = "CONTEXT7_API_KEY"

CTX7_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = CTX7_ROOT / ".env"


def load_environment() -> str | None:
    """Load ``tools/ctx7/.env`` if present. Return that path, or None."""
    load_dotenv(ENV_PATH, override=False)
    if ENV_PATH.is_file():
        return str(ENV_PATH)
    return None


def get_normalized_api_key() -> str:
    """``CONTEXT7_API_KEY`` from the environment, stripped. Empty string means "no key".

    Never treated as an error condition by this package -- callers pass the
    result straight to ``ctx7_core.client`` functions, which omit the
    ``Authorization`` header entirely when this is falsy.
    """
    return os.getenv(API_KEY_ENV, "").strip()
