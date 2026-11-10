#!/usr/bin/env python3
"""GitHub App の installation access token を取得する。

JWT（RS256、有効期限は最大10分のところ9分で発行）でアプリ自身として認証した上で
`POST /app/installations/{installation_id}/access_tokens` を叩き、1時間有効の
installation access token を取得する。

コンテナ起動のたびに新規取得する想定で、ディスクへの永続キャッシュは行わない
（1 ISSUE = 1 使い捨てコンテナ運用のため）。

環境変数（プロセス環境のみ。`.env` は読まない。ホスト常駐の `poller.py` は
`orchestrator/.env` を読む）:
    GITHUB_APP_ID                  GitHub App ID
    GITHUB_APP_PRIVATE_KEY_PATH    秘密鍵（PEM）ファイルへのパス
    GITHUB_APP_INSTALLATION_ID     Installation ID

使い方:
    python get_installation_token.py
        -> 標準出力にトークン文字列のみを出力する
    python get_installation_token.py --json
        -> {"token": ..., "expires_at": ...} をJSON出力する
    python get_installation_token.py --repo owner/repo
        -> トークンの対象リポジトリを絞り込む（複数指定可）

参照: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

import jwt  # PyJWT[crypto] -- RS256署名にcryptographyパッケージを使う

GITHUB_API_BASE = "https://api.github.com"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"error: 環境変数 {name} が未設定です")
    return value


def read_private_key(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        sys.exit(f"error: 秘密鍵ファイル {path} を読み込めません: {exc}")


def build_app_jwt(app_id: str, private_key_pem: str) -> str:
    """アプリ自身として認証するための短命JWT（RS256）を生成する。"""
    now = int(time.time())
    payload = {
        "iat": now - 60,  # クロックドリフト対策としてGitHub公式が推奨する60秒バックデート
        "exp": now + 9 * 60,  # 上限10分のうち余裕を見て9分
        "iss": app_id,
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


def fetch_installation_token(app_jwt: str, installation_id: str, repositories=None) -> dict:
    url = f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"
    body = json.dumps({"repositories": repositories} if repositories else {}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        sys.exit(f"error: installation token取得に失敗しました (HTTP {exc.code}): {detail}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--json", action="store_true", help="トークンだけでなくexpires_at等を含むJSONを出力する"
    )
    parser.add_argument(
        "--repo",
        action="append",
        dest="repositories",
        metavar="OWNER/REPO",
        help="トークンの対象リポジトリを絞り込む（複数指定可）。省略時はAppインストール範囲の全リポジトリ",
    )
    args = parser.parse_args()

    app_id = _require_env("GITHUB_APP_ID")
    private_key_pem = read_private_key(_require_env("GITHUB_APP_PRIVATE_KEY_PATH"))
    installation_id = _require_env("GITHUB_APP_INSTALLATION_ID")

    app_jwt = build_app_jwt(app_id, private_key_pem)
    result = fetch_installation_token(app_jwt, installation_id, args.repositories)

    if args.json:
        print(json.dumps({"token": result["token"], "expires_at": result["expires_at"]}))
    else:
        print(result["token"])


if __name__ == "__main__":
    main()
