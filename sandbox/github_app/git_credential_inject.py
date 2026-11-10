#!/usr/bin/env python3
"""installation access token をgitのHTTPS認証に使えるよう、remote URLへ埋め込む。

`https://x-access-token:<TOKEN>@github.com/owner/repo.git` 形式へ書き換える
（GitHub App installation tokenのgit認証形式）。

トークンをコマンドライン引数として渡すとプロセス一覧（`ps`等）に平文で映る
リスクがあるため、標準入力から読み取る。コンテナは1 ISSUE = 1使い捨て・
非rootの単一ユーザーで動かす前提のため、このリスクは許容範囲としている。

使い方:
    echo "$TOKEN" | python git_credential_inject.py <repo-dir> <owner/repo>
    get_installation_token.py | python git_credential_inject.py <repo-dir> <owner/repo>
"""

import argparse
import subprocess
import sys


def inject(repo_dir: str, owner_repo: str, token: str, remote: str) -> None:
    url = f"https://x-access-token:{token}@github.com/{owner_repo}.git"
    subprocess.run(
        ["git", "-C", repo_dir, "remote", "set-url", remote, url],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("repo_dir", help="git remoteを書き換える対象のローカルリポジトリパス")
    parser.add_argument("owner_repo", help="owner/repo形式（例: fdshg693/AI）")
    parser.add_argument("--remote", default="origin", help="書き換えるremote名（既定: origin）")
    args = parser.parse_args()

    token = sys.stdin.readline().strip()
    if not token:
        sys.exit("error: 標準入力からトークンを読み取れませんでした")

    inject(args.repo_dir, args.owner_repo, token, args.remote)
    print(f"{args.repo_dir} の remote '{args.remote}' を書き換えました")


if __name__ == "__main__":
    main()
