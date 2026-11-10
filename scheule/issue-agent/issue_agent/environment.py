""".env読み込み。`tools/issue-agent/.env`（gitignore対象、`*.env`パターン）を
`ISSUE_AGENT_ROOT`基準の固定パスで解決する。

カレントディレクトリ探索ではなく固定パスにしているのは、
`check.ps1`（`tools/schedule`経由、cwd=tools/issue-agent）と`uv run python -m
issue_agent.check`をリポジトリルート等どこから叩いても同じ`.env`を拾えるように
するため（`tools/aim/aim_cli.py`と同じ方針）。既存の環境変数を`.env`の値で
上書きしない（`override=False`）。
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

ISSUE_AGENT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ISSUE_AGENT_ROOT / ".env"


def load_environment() -> None:
    load_dotenv(ENV_PATH, override=False)
