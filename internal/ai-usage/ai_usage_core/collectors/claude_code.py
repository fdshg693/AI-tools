"""Claude Code collector: reads the statusLine hook's JSONL log for the latest
rate-limit snapshot (see ../../statusline_hook.py).

Claude Code has no pull API for rate limits, so this only reflects whatever the
most recent `statusline_hook.py` invocation logged -- i.e. a snapshot from the
last session, possibly stale. A window's `used_percent` is reported as
unavailable once its own `resets_at` has passed, since the window has reset
since the log entry was written.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ai_usage_core import config

_WINDOW_KEYS = (("five_hour", "5h"), ("seven_day", "7d"))


def _read_last_record(log_path: Path) -> dict | None:
    if not log_path.exists():
        return None
    last_line = None
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                last_line = line
    if last_line is None:
        return None
    try:
        return json.loads(last_line)
    except json.JSONDecodeError:
        return None


def collect(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    record = _read_last_record(config.get_claude_code_log_path()) or {}

    windows = []
    for key, name in _WINDOW_KEYS:
        window = record.get(key) or {}
        used_percent = window.get("used_percentage")
        resets_at = window.get("resets_at")
        if used_percent is None:
            windows.append({"name": name, "used_percent": None, "resets_at": None})
            continue
        stale = resets_at is not None and now >= resets_at
        windows.append(
            {
                "name": name,
                "used_percent": None if stale else used_percent,
                "resets_at": resets_at,
            }
        )

    return {"tool": "claude-code", "windows": windows}
