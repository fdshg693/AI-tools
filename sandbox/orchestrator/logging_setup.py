#!/usr/bin/env python3
"""オーケストレーターのロギング初期化。

コンソール（人間可読テキスト）+ ファイル（JSON Lines、日次ローテーション）の
2ハンドラ構成。ホスト側（`poller.py`）はファイルハンドラも使うが、コンテナ側
（`run_agent.py`の`--container-mode`）は使い捨てコンテナ内にログを残しても
`--rm`で消えるだけなので、`log_dir=None`でコンソールハンドラのみ有効にする。

ISSUE番号の相関は`current_issue_number`という`contextvars.ContextVar`で持ち、
`IssueContextFilter`がログレコードへ`issue_number`属性として自動注入する。
`github_client.py`等の既存の関数シグネチャへissue_numberを都度渡さずに済ませる
ための設計（渡し忘れによる相関ID抜けを防ぐ）。

`TokenRedactionFilter`は、フォーマット後のログメッセージ全文に対して正規表現で
token文字列らしきパターンを伏字化する安全網。`run_agent.py`の`_redact()`
（コマンド引数列だけが対象のピンポイント対策）とは別に、全ハンドラ共通で
両方併存させる多層防御。
"""

import contextlib
import contextvars
import json
import logging
import logging.handlers
import re
import sys
from pathlib import Path

ORCHESTRATOR_DIR = Path(__file__).resolve().parent
DEFAULT_LOG_DIR = "data/logs"

current_issue_number: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_issue_number", default=None
)


def resolve_log_dir(raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else ORCHESTRATOR_DIR / path


@contextlib.contextmanager
def issue_context(issue_number: int):
    """このwithブロック内のログレコードへ`issue_number`を自動で乗せる。"""
    token = current_issue_number.set(issue_number)
    try:
        yield
    finally:
        current_issue_number.reset(token)


class IssueContextFilter(logging.Filter):
    """`current_issue_number`の値をログレコードへ`issue_number`属性として注入する。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.issue_number = current_issue_number.get()
        return True


# GitHub App installation token（`ghs_`）、GitHub PAT（`gh[opu]_`/`github_pat_`）、
# Basic/Bearer認証ヘッダーの値部分など、うっかりf-stringでログに乗りうる
# token様文字列を伏字化する。
_TOKEN_PATTERNS = [
    re.compile(r"gh[opsu]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)(authorization:\s*basic\s+)[A-Za-z0-9+/=]{20,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-\._~+/]{20,}"),
]


def _redact_match(match: re.Match) -> str:
    groups = match.groups()
    if groups:
        return f"{groups[0]}***"
    return "***"


class TokenRedactionFilter(logging.Filter):
    """フォーマット後メッセージ全体を対象にした正規表現ベースのtoken伏字化。"""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = message
        for pattern in _TOKEN_PATTERNS:
            redacted = pattern.sub(_redact_match, redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


class JsonLinesFormatter(logging.Formatter):
    """ファイルハンドラ用: 1レコード1行のJSONに整形する。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "issue_number": getattr(record, "issue_number", None),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(
    level: str = "INFO", log_dir: Path | None = None, retention_days: int = 14
) -> None:
    """ルートロガーへコンソール（+ 任意でファイル）ハンドラを設定する。

    `log_dir`が`None`の場合はコンソールハンドラのみ（コンテナ側の軽量初期化用）。
    複数回呼び出しても冪等になるよう、既存ハンドラは毎回クリアする。
    """
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    issue_filter = IssueContextFilter()
    token_filter = TokenRedactionFilter()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [issue=%(issue_number)s] %(name)s: %(message)s"
        )
    )
    console_handler.addFilter(issue_filter)
    console_handler.addFilter(token_filter)
    root.addHandler(console_handler)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            log_dir / "orchestrator.log",
            when="midnight",
            backupCount=retention_days,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonLinesFormatter())
        file_handler.addFilter(issue_filter)
        file_handler.addFilter(token_filter)
        root.addHandler(file_handler)
