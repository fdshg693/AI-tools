"""claude-wrapper ルートを sys.path に入れ、`util` を import できるようにする。"""

from __future__ import annotations

import sys
from pathlib import Path

WRAPPER_ROOT = Path(__file__).resolve().parents[1]
_root = str(WRAPPER_ROOT)
if _root not in sys.path:
    sys.path.insert(0, _root)
