#!/usr/bin/env python3
"""GitHub REST/Search API の薄いラッパー。

`@sandbox` メンションを含むISSUEの検索・ISSUE本文/コメント取得（メンション実行者の
`author_association`判定向け）・対応PRの有無確認・失敗コメント投稿・PR作成のみを扱う。
`tools/sandbox/github_app/get_installation_token.py` と同じく
stdlibの`urllib`のみで実装し、PyGithub等の追加依存は持ち込まない。
"""

import json
import urllib.error
import urllib.parse
import urllib.request

GITHUB_API_BASE = "https://api.github.com"


class GitHubApiError(RuntimeError):
    """GitHub APIがエラーレスポンスを返した場合に送出する。"""


def _request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    url = path if path.startswith("http") else f"{GITHUB_API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GitHubApiError(f"{method} {url} failed (HTTP {exc.code}): {detail}") from exc


def search_mentioning_issues(
    token: str, owner: str, repo: str, mention: str = "@sandbox"
) -> list[dict]:
    """本文またはコメントに`mention`を含む、open状態のISSUEを検索する。"""
    query = f'repo:{owner}/{repo} is:issue is:open "{mention}" in:body,comments'
    params = urllib.parse.urlencode({"q": query})
    result = _request("GET", f"/search/issues?{params}", token)
    return result.get("items", [])


def get_issue(token: str, owner: str, repo: str, issue_number: int) -> dict:
    """ISSUE本文・作成者の`author_association`等を取得する（メンション実行者判定向け）。"""
    return _request("GET", f"/repos/{owner}/{repo}/issues/{issue_number}", token)


def get_issue_comments(token: str, owner: str, repo: str, issue_number: int) -> list[dict]:
    """ISSUEの全コメントを取得する（メンション実行者判定向け。ページングは考慮しない —
    本エージェントが処理するのはメンション検出直後のISSUEのみで、コメント数が
    デフォルトページサイズ（100件）を超えるケースは想定していない）。"""
    return _request("GET", f"/repos/{owner}/{repo}/issues/{issue_number}/comments", token)


def has_existing_pr_for_branch(token: str, owner: str, repo: str, branch: str) -> bool:
    """指定ブランチをheadとするPR（open/closed問わず）が既に存在するか確認する。

    「処理済み」= そのISSUE用のPRが既に作られているかどうかで判定し、ワーカー側に
    ローカルの既読状態ファイルは持たせない（GitHub側を単一の真実源にする決定事項）。
    """
    params = urllib.parse.urlencode({"head": f"{owner}:{branch}", "state": "all"})
    prs = _request("GET", f"/repos/{owner}/{repo}/pulls?{params}", token)
    return len(prs) > 0


def create_pull_request(
    token: str, owner: str, repo: str, branch: str, base: str, title: str, body: str
) -> dict:
    return _request(
        "POST",
        f"/repos/{owner}/{repo}/pulls",
        token,
        body={"title": title, "head": branch, "base": base, "body": body},
    )


def create_issue_comment(token: str, owner: str, repo: str, issue_number: int, body: str) -> dict:
    return _request(
        "POST",
        f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
        token,
        body={"body": body},
    )
