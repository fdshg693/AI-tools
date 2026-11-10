"""CLIエントリポイント。`check.py`から`python -m issue_agent.worker --issue-number N`
として呼ばれる。ISSUE取得 → dispatch解決 → worktree作成 → Claude起動 → commit確認
→ PR実在確認 → ISSUEコメント返信 → worktree後片付け → 結果をJSON1行で標準出力に出す、
までを一貫して行う（worker本体）。

PRが実際に作られたかどうかは、Claudeの最終応答テキストではなく`gh pr list --head
<branch>`（`github_ops.get_pr_for_branch()`）の実行結果で判定する。commitがあっても
PRが見つからなければ失敗扱いにする（00-overview.mdの決定事項: Claudeの自己申告を
鵜呑みにしない）。ISSUEへのコメント投稿もこのモジュール自身が行い、Claudeにはやらせない。
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

from . import dispatch, github_ops, worktree
from .config import Config
from .environment import load_environment

logger = logging.getLogger(__name__)


def _rev_parse_head(workdir: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(workdir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def _commit_count(workdir: Path, base_sha: str) -> int:
    result = subprocess.run(
        ["git", "-C", str(workdir), "rev-list", "--count", f"{base_sha}..HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return int(result.stdout.strip())


def _build_issue_comment(result: dict, branch: str | None) -> str:
    session_line = (
        f"セッション識別子: {result['session_id']}"
        if result["session_id"]
        else "セッション識別子: (エージェント未起動)"
    )
    if result["success"]:
        return "\n".join(
            [
                "自動対応が完了しました。",
                "",
                session_line,
                f"作業ブランチ: {branch}",
                f"PR: {result['pr_url']}",
            ]
        )
    lines = ["自動対応に失敗しました。", "", session_line]
    if branch is not None:
        lines.append(f"作業ブランチ: {branch}")
    lines.append(f"エラー内容: {result['detail']}")
    return "\n".join(lines)


def _report_and_cleanup(
    config: Config, issue_number: int, branch: str, workdir: Path | None, result: dict
) -> None:
    """成否を問わずISSUEへコメントし、workdirが作られていれば後片付けする。

    コメント投稿・worktree後片付けそのものの失敗はログに残すのみで、`result`の
    成否（実際の作業結果）には影響させない。
    """
    body = _build_issue_comment(result, branch if workdir is not None else None)
    try:
        github_ops.create_issue_comment(config.owner, config.repo, issue_number, body)
    except github_ops.GitHubOpsError as exc:
        logger.error(f"issue #{issue_number}: ISSUEコメント投稿に失敗しました: {exc}")

    if workdir is None:
        return
    try:
        worktree.cleanup(workdir, keep=not result["success"])
    except worktree.WorktreeError as exc:
        logger.error(f"issue #{issue_number}: worktree後片付けに失敗しました: {exc}")


def run_worker(config: Config, issue_number: int) -> dict:
    result = {
        "issue_number": issue_number,
        "success": False,
        "session_id": None,
        "commit_count": 0,
        "pr_url": None,
        "detail": "",
    }
    branch = worktree.branch_name(issue_number)
    workdir: Path | None = None

    try:
        issue = github_ops.get_issue(config.owner, config.repo, issue_number)
        labels = [label["name"] for label in issue.get("labels", [])]

        tool_label = dispatch.resolve_tool_label(labels)
        model = dispatch.resolve_model_label(labels)
        handler = dispatch.resolve_handler(tool_label)

        workdir = worktree.create(issue_number)
        base_sha = _rev_parse_head(workdir)

        logger.info(f"issue #{issue_number}: starting agent (model={model}, workdir={workdir})")
        invocation = handler(issue=issue, workdir=workdir, model=model)
        result["session_id"] = invocation.session_id

        if invocation.subtype != "success":
            result["detail"] = f"エージェントが異常終了しました（subtype={invocation.subtype}）"
        else:
            commit_count = _commit_count(workdir, base_sha)
            result["commit_count"] = commit_count
            pr = github_ops.get_pr_for_branch(config.owner, config.repo, branch)
            if pr is not None:
                result["success"] = True
                result["pr_url"] = pr["url"]
                result["detail"] = f"PRを作成しました: {pr['url']}"
            elif commit_count == 0:
                result["detail"] = (
                    f"変更がコミットされませんでした。エージェントの最終応答: {invocation.last_text}"
                )
            else:
                result["detail"] = (
                    f"{commit_count}件のコミットはありましたが、PRが作成されませんでした"
                    "（エージェントがPR作成の指示に従わなかった可能性があります）"
                )
    except dispatch.DispatchError as exc:
        result["detail"] = str(exc)
    except (github_ops.GitHubOpsError, worktree.WorktreeError) as exc:
        result["detail"] = f"実行時エラー: {exc}"
    except Exception as exc:  # 失敗理由を確実にJSON化して結果として残すための最終防御
        result["detail"] = f"想定外のエラー: {exc}"

    _report_and_cleanup(config, issue_number, branch, workdir, result)
    return result


def main() -> None:
    load_environment()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    parser = argparse.ArgumentParser(
        description="ISSUE1件についてworktree作成〜Claude起動〜commit確認までを行うworker"
    )
    parser.add_argument("--issue-number", type=int, required=True)
    args = parser.parse_args()

    config = Config.from_env()
    result = run_worker(config, args.issue_number)
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
