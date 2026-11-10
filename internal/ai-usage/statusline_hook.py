#!/usr/bin/env python3
"""Claude Code `statusLine` hook: registered in the user's global `~/.claude/settings.json`
(not project settings) so it captures rate-limit usage across every repo, not just this one.

Reads the session JSON Claude Code sends on stdin, appends a rate-limit snapshot to
`~/.ai-usage/claude-code-rate-limits.jsonl` when `rate_limits` is present, and prints a
short status line (model name + 5h/7d usage %). `rate_limits` is absent before the first
API response in a session, so most invocations only print -- they don't log.

Must never fail the status line itself: any error here is swallowed and a minimal
fallback line is printed instead, since a hook exiting non-zero or raising blanks out
Claude Code's whole status line display.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_usage_core import config  # noqa: E402


def _append_log(rate_limits: dict) -> None:
    five_hour = rate_limits.get("five_hour") or {}
    seven_day = rate_limits.get("seven_day") or {}
    if five_hour.get("used_percentage") is None and seven_day.get("used_percentage") is None:
        return

    record = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "five_hour": {
            "used_percentage": five_hour.get("used_percentage"),
            "resets_at": five_hour.get("resets_at"),
        },
        "seven_day": {
            "used_percentage": seven_day.get("used_percentage"),
            "resets_at": seven_day.get("resets_at"),
        },
    }
    log_path = config.get_claude_code_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _render(data: dict) -> str:
    model = (data.get("model") or {}).get("display_name", "?")
    rate_limits = data.get("rate_limits") or {}
    five_hour = (rate_limits.get("five_hour") or {}).get("used_percentage")
    seven_day = (rate_limits.get("seven_day") or {}).get("used_percentage")

    parts = []
    if five_hour is not None:
        parts.append(f"5h: {five_hour:.0f}%")
    if seven_day is not None:
        parts.append(f"7d: {seven_day:.0f}%")

    return f"[{model}] {' '.join(parts)}" if parts else f"[{model}]"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("[?]")
        return 0

    try:
        rate_limits = data.get("rate_limits")
        if rate_limits:
            _append_log(rate_limits)
    except Exception:
        pass

    try:
        print(_render(data))
    except Exception:
        print("[?]")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
