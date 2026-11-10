"""Make ``icw_core`` / ``toy_repl`` importable without requiring an editable
install first (mirrors ``tools/ctx7/tests``'s ``sys.path`` insertion), so
``uv run pytest tools/interactive-cli-wrapper`` works right after cloning.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
