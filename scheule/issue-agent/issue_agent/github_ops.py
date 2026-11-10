"""`gh` CLIをsubprocess経由で呼ぶ薄いラッパー。

ホスト上で直接動く前提（Docker越しではない）のため、`tools/sandbox`のようにGitHub App
tokenをurllibで扱う必要はなく、ホストに既にログイン済みの`gh` CLIをそのまま使う
（00-overview.mdの決定事項）。PRの実在確認関数は04で追加する。`gh pr create`はClaude
自身がBashツール経由で叩くためこのラッパーには含めない。
"""

from __future__ import annotations

import json
import subprocess


class GitHubOpsError(RuntimeError):
    """`gh`コマンドが非ゼロ終了した場合に送出する。"""


def _run_gh(args: list[str], input: str | None = None) -> str:
    result = subprocess.run(
        ["gh", *args], input=input, capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        raise GitHubOpsError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def list_issues_with_label(owner: str, repo: str, label: str) -> list[dict]:
    """指定ラベルが付いたopen issueを取得する（ラベル値ごとに叩く。全文検索はしない）。"""
    out = _run_gh(
        [
            "issue",
            "list",
            "--repo",
            f"{owner}/{repo}",
            "--label",
            label,
            "--state",
            "open",
            "--json",
            "number,title,body,labels",
        ]
    )
    return json.loads(out) if out.strip() else []


def get_issue(owner: str, repo: str, issue_number: int) -> dict:
    """指定ISSUEのtitle/body/labelsを取得する。

    `worker.py`は`--issue-number`しか受け取らないため、自分でこの関数を呼んで
    ISSUE本文を取得する（`check.py`が検索時に取得した内容をsubprocess引数として
    引き継がない設計）。
    """
    out = _run_gh(
        [
            "issue",
            "view",
            str(issue_number),
            "--repo",
            f"{owner}/{repo}",
            "--json",
            "number,title,body,labels",
        ]
    )
    return json.loads(out)


def get_last_label_actor(owner: str, repo: str, issue_number: int, label: str) -> str | None:
    """`label`を最後に付与したユーザーのログインを返す（複数回付け外しされた場合は最後のもの）。"""
    jq_filter = f'[.[] | select(.event=="labeled" and .label.name=="{label}")][-1].actor.login'
    out = _run_gh(["api", f"repos/{owner}/{repo}/issues/{issue_number}/events", "--jq", jq_filter])
    login = out.strip()
    return login or None


def get_collaborator_logins(owner: str, repo: str) -> frozenset[str]:
    out = _run_gh(["api", f"repos/{owner}/{repo}/collaborators", "--jq", ".[].login"])
    return frozenset(line.strip() for line in out.splitlines() if line.strip())


def get_pr_for_branch(owner: str, repo: str, branch: str) -> dict | None:
    """`branch`をheadとするPRが存在すれば返す（無ければNone）。

    `state`は指定せず`gh pr list`の既定（open）のみを見る。Claudeが今回の実行で
    作成したPRの有無を確認する用途のため、過去に閉じられたPRまで拾う必要はない
    （04-pr-creation-issue-reply-and-cleanup.mdの決定事項: 成否判定はこの結果で行う）。
    """
    out = _run_gh(
        [
            "pr",
            "list",
            "--repo",
            f"{owner}/{repo}",
            "--head",
            branch,
            "--json",
            "url,number,state",
        ]
    )
    prs = json.loads(out) if out.strip() else []
    return prs[0] if prs else None


def create_issue_comment(owner: str, repo: str, issue_number: int, body: str) -> None:
    """コメント本文はコマンドライン引数ではなくstdin(`--body-file -`)経由で渡す。

    長文・複数行本文でのWindows上のクォート崩れ/コマンドライン長制限を避けるため。
    """
    _run_gh(
        ["issue", "comment", str(issue_number), "--repo", f"{owner}/{repo}", "--body-file", "-"],
        input=body,
    )
