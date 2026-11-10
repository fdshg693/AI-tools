"""エージェント実行ログの書き出し。

呼び出し1回につき、時刻昇順でソート可能なファイル名で1ファイルを書く。
ツール結果(ToolMessage)は記録せず、入力・ツール呼び出し・最終回答のみ残す。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import AIMessage, BaseMessage

# tools/my-agents/logs/ （実行時カレントに依存しない）
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"

_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\s]+')


def _sanitize_agent_name(name: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", name).strip("._")
    return cleaned or "agent"


def _extract_tool_calls(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for tool_call in message.tool_calls or []:
            entry: dict[str, Any] = {"name": tool_call.get("name", "")}
            args = tool_call.get("args")
            if args is not None:
                entry["args"] = args
            calls.append(entry)
    return calls


def build_run_log_payload(
    *,
    agent_name: str,
    model: str,
    prompt: str,
    messages: list[BaseMessage],
    final_answer: str,
    started_at: datetime,
) -> dict[str, Any]:
    """ログファイルに書く辞書を組み立てる（ツール結果は含めない）。"""
    return {
        "agent": agent_name,
        "model": model,
        "started_at": started_at.isoformat(timespec="microseconds"),
        "input": prompt,
        "tool_calls": _extract_tool_calls(messages),
        "final_answer": final_answer,
    }


def write_run_log(
    *,
    agent_name: str,
    model: str,
    prompt: str,
    messages: list[BaseMessage],
    final_answer: str,
    logs_dir: Path | None = None,
    started_at: datetime | None = None,
) -> Path:
    """実行ログを1ファイル書き出し、そのパスを返す。

    ファイル名は ``YYYYMMDDTHHMMSS_ffffff_<agent>.yaml`` で、辞書順＝時刻昇順になる。
    """
    started = started_at or datetime.now().astimezone()
    dest_dir = logs_dir if logs_dir is not None else LOGS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    stamp = started.strftime("%Y%m%dT%H%M%S_%f")
    filename = f"{stamp}_{_sanitize_agent_name(agent_name)}.yaml"
    path = dest_dir / filename

    payload = build_run_log_payload(
        agent_name=agent_name,
        model=model,
        prompt=prompt,
        messages=messages,
        final_answer=final_answer,
        started_at=started,
    )
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path
