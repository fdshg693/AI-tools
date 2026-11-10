"""ISSUE専用git worktreeの作成・削除ラッパー。

配置場所はリポジトリの**外側**（親ディレクトリ配下、既定`<repo親>/ai-worktrees/issue-<N>`、
`ISSUE_AGENT_WORKTREE_ROOT`環境変数で上書き可能）にする。メインの作業ツリー内部
（例: `temp/`配下）に置くと、通常のgit操作やこのリポジトリ自身の各種チェック
スクリプトが誤って巻き込まれるため、標準的なgit worktreeの使い方（兄弟ディレクトリ）
に従う（03-worktree-and-agent-worker.md 決定事項）。

worktreeの削除は本モジュールが提供するのみで、いつ呼ぶか（push成功後に消すか、
失敗時は調査のため残すか）は04（後片付けステップ）側の責務。
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from .attempt_store import ISSUE_AGENT_ROOT

logger = logging.getLogger(__name__)

REPO_ROOT = ISSUE_AGENT_ROOT.parent.parent
DEFAULT_WORKTREE_ROOT = REPO_ROOT.parent / "ai-worktrees"


class WorktreeError(RuntimeError):
    """`git worktree`コマンドが失敗した場合に送出する。"""


def _run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        raise WorktreeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def worktree_root() -> Path:
    raw = os.environ.get("ISSUE_AGENT_WORKTREE_ROOT")
    return Path(raw) if raw and raw.strip() else DEFAULT_WORKTREE_ROOT


def branch_name(issue_number: int) -> str:
    return f"issue-agent/issue-{issue_number}"


def create(issue_number: int) -> Path:
    """ISSUE専用worktreeを作成し、そのパスを返す。

    同名のworktreeが既に残っている場合（前回試行の後片付け漏れ等）は、
    `-B`で既存ブランチを現在のHEADへリセットしつつ作り直す前提のため、
    先に既存worktreeを取り除く。
    """
    root = worktree_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"issue-{issue_number}"
    if path.exists():
        remove(path)
    _run_git(["worktree", "add", "-B", branch_name(issue_number), str(path), "HEAD"])
    return path


def remove(path: Path) -> None:
    _run_git(["worktree", "remove", "--force", str(path)])


def cleanup(path: Path, *, keep: bool) -> None:
    """呼び出し側（worker.py）が決めた成否に応じてworktreeを片付ける。

    `keep=True`の場合は`remove()`を呼ばず残す（PRが実在しなかった失敗ケースで
    調査用に作業内容を残す。04-pr-creation-issue-reply-and-cleanup.mdの決定事項）。
    """
    if keep:
        logger.info(f"PR未作成のためworktreeを保持します（調査用）: {path}")
        return
    remove(path)
