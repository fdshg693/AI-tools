"""Make ``ona_run_cli`` importable without requiring an editable install first
(mirrors ``tools/interactive-cli-wrapper/tests/conftest.py``), so
``uv run pytest tools/ona-run`` works right after cloning.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
