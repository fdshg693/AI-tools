"""環境変数駆動の設定。`tools/sandbox/orchestrator/poller.py`の`Config.from_env()`と同じ形。"""

from __future__ import annotations

import os

from pydantic import BaseModel

DEFAULT_OWNER = "fdshg693"
DEFAULT_REPO = "AI"
DEFAULT_TOOL_LABEL = "tool:claude-code"
DEFAULT_STATE_DB_PATH = "data/state.db"
DEFAULT_LOG_DIR = "data/logs"
DEFAULT_MAX_ISSUES_PER_CYCLE = 1
DEFAULT_WORKER_TIMEOUT_SECONDS = 1200


def _env_or_default(name: str, default: str) -> str:
    """未設定・空文字/空白のみの場合もデフォルトへフォールバックする。"""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


class Config(BaseModel):
    """`check.py`が1周期分の処理に使う設定値。"""

    owner: str = DEFAULT_OWNER
    repo: str = DEFAULT_REPO
    # 検索対象のtool:ラベル一覧。dispatchテーブル(03で実装)が実際に対応できるラベルは
    # supported_tool_labelsの部分集合。両者を分けておくことで、対応予定だが未実装の
    # ラベルを先に検索対象へ加え、「未対応ラベル」として一言コメントする運用ができる。
    tracked_tool_labels: tuple[str, ...] = (DEFAULT_TOOL_LABEL,)
    supported_tool_labels: frozenset[str] = frozenset({DEFAULT_TOOL_LABEL})
    # Noneの場合はcheck.pyがgithub_ops.get_collaborator_logins()で毎周期動的に取得する。
    allowed_logins: frozenset[str] | None = None
    max_issues_per_cycle: int = DEFAULT_MAX_ISSUES_PER_CYCLE
    worker_timeout_seconds: int = DEFAULT_WORKER_TIMEOUT_SECONDS
    state_db_path: str = DEFAULT_STATE_DB_PATH
    log_dir: str = DEFAULT_LOG_DIR

    @classmethod
    def from_env(cls) -> Config:
        allowed_raw = os.environ.get("ISSUE_AGENT_ALLOWED_LOGINS")
        allowed_logins = (
            frozenset(_split_csv(allowed_raw)) if allowed_raw and allowed_raw.strip() else None
        )

        return cls(
            owner=_env_or_default("ISSUE_AGENT_OWNER", DEFAULT_OWNER),
            repo=_env_or_default("ISSUE_AGENT_REPO", DEFAULT_REPO),
            tracked_tool_labels=_split_csv(
                _env_or_default("ISSUE_AGENT_TOOL_LABELS", DEFAULT_TOOL_LABEL)
            ),
            supported_tool_labels=frozenset(
                _split_csv(_env_or_default("ISSUE_AGENT_SUPPORTED_TOOL_LABELS", DEFAULT_TOOL_LABEL))
            ),
            allowed_logins=allowed_logins,
            max_issues_per_cycle=int(
                _env_or_default(
                    "ISSUE_AGENT_MAX_ISSUES_PER_CYCLE", str(DEFAULT_MAX_ISSUES_PER_CYCLE)
                )
            ),
            worker_timeout_seconds=int(
                _env_or_default(
                    "ISSUE_AGENT_WORKER_TIMEOUT_SECONDS", str(DEFAULT_WORKER_TIMEOUT_SECONDS)
                )
            ),
            state_db_path=_env_or_default("ISSUE_AGENT_STATE_DB_PATH", DEFAULT_STATE_DB_PATH),
            log_dir=_env_or_default("ISSUE_AGENT_LOG_DIR", DEFAULT_LOG_DIR),
        )
