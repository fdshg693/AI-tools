"""チェックスクリプト本体。1回の実行で1周期分だけ処理して終了する（`while True`は持たない。
繰り返しは`tools/schedule`のタスクスケジューラintervalに委ねる。00-overview.mdの決定事項）。

周期ごとの流れ:
  1. `config.tracked_tool_labels`の各ラベルについて、そのラベルが付いたopen issueを検索する
  2. ラベルが`config.supported_tool_labels`に含まれない場合は「対応不可」として記録・コメントし、
     以後再試行しない
  3. ラベルを最後に付けたユーザーがcollaboratorかどうかで認可判定する。認可されない場合は
     試行記録を残さずスキップする（将来collaboratorになった場合などに再試行可能にするため）
  4. `attempt_store`で未試行のissueだけ、`python -m issue_agent.worker`をsubprocessで
     **同期呼び出し**する（stdout/stderrはissue単位のログファイルに保存する）
  5. 結果を`attempt_store`に記録する

worktree作成・Claude Agent SDK起動そのもの（worker本体）は03で実装する。
"""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import github_ops
from .attempt_store import ISSUE_AGENT_ROOT, AttemptStore, resolve_db_path
from .config import Config
from .environment import load_environment

logger = logging.getLogger(__name__)


def resolve_log_dir(raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else ISSUE_AGENT_ROOT / path


def _handle_unsupported_label(
    store: AttemptStore, config: Config, issue_number: int, label: str
) -> None:
    if not store.record_attempt_start(issue_number):
        return
    detail = f"未対応のツールラベルです: {label}"
    github_ops.create_issue_comment(
        config.owner,
        config.repo,
        issue_number,
        body=f"`{label}` は現時点で対応していないツールラベルのため、自動処理をスキップしました。",
    )
    store.record_attempt_result(issue_number, success=False, detail=detail)
    logger.info(f"issue #{issue_number}: {detail}")


def _is_authorized(config: Config, actor: str | None) -> bool:
    if actor is None:
        return False
    allowed = (
        config.allowed_logins
        if config.allowed_logins is not None
        else github_ops.get_collaborator_logins(config.owner, config.repo)
    )
    return actor in allowed


def _run_worker(config: Config, issue_number: int, log_dir: Path) -> tuple[bool, str, str]:
    """workerをsubprocessで同期呼び出しする。戻り値は(success, detail, log_file)。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_file = log_dir / f"issue-{issue_number}-{timestamp}.log"

    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "issue_agent.worker",
                "--issue-number",
                str(issue_number),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=config.worker_timeout_seconds,
        )
        log_file.write_text(result.stdout + result.stderr, encoding="utf-8")
        success = result.returncode == 0
        detail = "worker succeeded" if success else f"worker exited with code {result.returncode}"
        return success, detail, str(log_file)
    except subprocess.TimeoutExpired as exc:
        combined = (exc.stdout or "") + (exc.stderr or "")
        log_file.write_text(combined, encoding="utf-8")
        return False, f"worker timed out after {config.worker_timeout_seconds}s", str(log_file)


def process_issue(
    store: AttemptStore, config: Config, issue: dict, label: str, log_dir: Path
) -> bool:
    """issue 1件を処理する。戻り値はworkerを実際に起動したか（1周期の上限カウント用）。"""
    issue_number = issue["number"]

    if label not in config.supported_tool_labels:
        _handle_unsupported_label(store, config, issue_number, label)
        return False

    actor = github_ops.get_last_label_actor(config.owner, config.repo, issue_number, label)
    if not _is_authorized(config, actor):
        logger.info(f"issue #{issue_number}: ラベル付与者({actor})が未認可のためスキップ")
        return False

    if not store.record_attempt_start(issue_number):
        logger.info(f"issue #{issue_number}: 試行済みのためスキップ（1 ISSUE = 1回までの制限）")
        return False

    logger.info(f"issue #{issue_number}: worker起動")
    success, detail, log_file = _run_worker(config, issue_number, log_dir)
    store.record_attempt_result(issue_number, success=success, detail=detail, log_file=log_file)
    logger.info(f"issue #{issue_number}: {detail} (log: {log_file})")
    return True


def check_once(store: AttemptStore, config: Config) -> None:
    log_dir = resolve_log_dir(config.log_dir)
    processed = 0
    for label in config.tracked_tool_labels:
        if processed >= config.max_issues_per_cycle:
            break
        issues = github_ops.list_issues_with_label(config.owner, config.repo, label)
        logger.info(f"label={label}: {len(issues)}件のopen issueを検出")
        for issue in issues:
            if processed >= config.max_issues_per_cycle:
                logger.info(
                    f"1周期あたりの上限(max_issues_per_cycle={config.max_issues_per_cycle})に"
                    "達したため、残りは次回チェックへ持ち越し"
                )
                break
            if process_issue(store, config, issue, label, log_dir):
                processed += 1


def main() -> None:
    load_environment()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout
    )
    config = Config.from_env()
    store = AttemptStore(resolve_db_path(config.state_db_path))
    logger.info(f"checking {config.owner}/{config.repo} for labels {config.tracked_tool_labels}")
    check_once(store, config)


if __name__ == "__main__":
    main()
