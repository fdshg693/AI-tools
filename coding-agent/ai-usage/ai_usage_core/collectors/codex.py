"""Codex collector: spawns `codex app-server` and speaks JSON-RPC over stdio
to fetch ChatGPT rate limits (`account/rateLimits/read`).

Pull-based, unlike the Claude Code collector: `codex app-server` is started
fresh for each `collect()` call and torn down afterward, no daemon is kept
running. `primary`/`secondary` aren't documented as fixed 5h/weekly windows,
so which is which is inferred here from `windowDurationMins` at call time
rather than assumed.
"""

from __future__ import annotations

import json
import shutil
import subprocess

_INITIALIZE_ID = 0
_RATE_LIMITS_ID = 1
_CLIENT_INFO = {"name": "ai-usage", "title": "ai-usage", "version": "0.1.0"}


def _label_for_window(duration_mins) -> str:
    if duration_mins is None:
        return "?"
    if duration_mins <= 360:
        return "5h"
    days = duration_mins / 1440
    if days >= 1:
        return f"{round(days)}d"
    return f"{round(duration_mins / 60)}h"


def _send(proc: subprocess.Popen, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _read_response(proc: subprocess.Popen, expected_id: int, max_lines: int = 50) -> dict | None:
    for _ in range(max_lines):
        line = proc.stdout.readline()
        if not line:
            return None
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == expected_id:
            return message
    return None


def _empty() -> dict:
    return {"tool": "codex", "windows": []}


def collect() -> dict:
    if shutil.which("codex") is None:
        return _empty()

    try:
        proc = subprocess.Popen(
            ["codex", "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return _empty()

    try:
        _send(
            proc,
            {"method": "initialize", "id": _INITIALIZE_ID, "params": {"clientInfo": _CLIENT_INFO}},
        )
        if _read_response(proc, _INITIALIZE_ID) is None:
            return _empty()

        _send(proc, {"method": "initialized", "params": {}})
        _send(proc, {"method": "account/rateLimits/read", "id": _RATE_LIMITS_ID})
        response = _read_response(proc, _RATE_LIMITS_ID)
    except Exception:
        return _empty()
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if not response or "result" not in response:
        return _empty()

    rate_limits = (response["result"] or {}).get("rateLimits") or {}
    windows = []
    for key in ("primary", "secondary"):
        window = rate_limits.get(key)
        if not window:
            continue
        windows.append(
            {
                "name": _label_for_window(window.get("windowDurationMins")),
                "used_percent": window.get("usedPercent"),
                "resets_at": window.get("resetsAt"),
            }
        )

    return {"tool": "codex", "windows": windows}
