"""Make ``ctx7_core`` / ``ctx7_cli`` importable without requiring an editable
install first (mirrors ``tools/tav-cli/tests``'s ``sys.path`` insertion), so
``uv run pytest tools/ctx7`` works right after cloning, before anyone runs
``uv tool install --editable tools/ctx7``.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
