# GitHub App作成手順

サンドボックスエージェント用GitHub Appを作成する手順（一度きりの手動セットアップ）。
コードでは自動化しない。作成後に得られる3つの値（App ID・Installation ID・秘密鍵）は
[../orchestrator/.env.example](../orchestrator/.env.example) の `GITHUB_APP_ID` /
`GITHUB_APP_INSTALLATION_ID` / `GITHUB_APP_PRIVATE_KEY_PATH` に対応する。

## 1. App登録

1. 対象リポジトリのオーナーアカウントで GitHub の
   `Settings > Developer settings > GitHub Apps > New GitHub App` を開く。
2. 以下を設定する。
   - **GitHub App name**: 任意（例: `ai-sandbox-agent`）。組織/ユーザー内で一意な名前が必要。
   - **Homepage URL**: 任意（例: リポジトリのURL）。
   - **Webhook**: `Active` のチェックを外す（ポーリング運用のためWebhook不要）。
3. **Repository permissions** で以下を設定する（最小権限。git pushには
   Contents:Write が必須なため Read のみでは不足する）。
   - **Contents**: `Read and write`
   - **Issues**: `Read and write`
   - **Pull requests**: `Read and write`
   - **Metadata**: `Read-only`（自動で必須付与される）
   - 他の権限はすべて `No access` のままにする。
4. **Where can this GitHub App be installed?** は `Only on this account` を選択する
   （対象リポジトリを固定運用する前提のため）。
5. `Create GitHub App` をクリックする。

## 2. App IDの確認

作成後のApp設定ページ上部に表示される **App ID**（数値）を控える。
→ `.env` の `GITHUB_APP_ID` に設定する。

## 3. 秘密鍵の生成・保存

1. App設定ページを下にスクロールし、**Private keys** セクションの
   `Generate a private key` をクリックする。
2. `.pem` ファイルがダウンロードされる。この内容は再表示不可・再ダウンロード不可なので、
   安全な場所（このマシン上の、コンテナに読み取り専用マウントできるパス）に保存する。
   **リポジトリにコミットしない**（`.gitignore` 対象パスに置くこと）。
3. コンテナ起動時にこのファイルをマウントし、そのマウント先パスを
   `.env` の `GITHUB_APP_PRIVATE_KEY_PATH` に設定する
   （マウント方法自体は`orchestrator/run_agent.py`側の実装を参照）。

## 4. リポジトリへのインストール・Installation IDの確認

1. App設定ページ左メニューの `Install App` を開き、対象アカウントの `Install` を押す。
2. `Only select repositories` を選び、対象リポジトリ（このAIリポジトリ）のみを選択して
   `Install` する。
3. インストール後、ブラウザのURLが
   `https://github.com/settings/installations/<INSTALLATION_ID>` のような形式になる
   （または `Settings > Applications > <App名>` の `Configure` から同じ画面に遷移できる）。
   この `<INSTALLATION_ID>` の数値を控える。
   → `.env` の `GITHUB_APP_INSTALLATION_ID` に設定する。

## 5. 動作確認

`tools/sandbox/github_app/get_installation_token.py` を、上記3値を環境変数に設定した上で
実行し、installation access tokenが取得できることを確認する。このCLIは `.env` を読まない
（`poller.py` だけが `orchestrator/.env` を読む）。詳細は
[../github_app/get_installation_token.py](../github_app/get_installation_token.py) のdocstring参照。

## 6. ブランチ保護との組み合わせ（前提の再掲）

このAppには Contents:Write を付与しているため、技術的には直接pushが可能。
mainブランチへの直接pushを防ぐのはApp権限ではなく**リポジトリ側のブランチ保護ルール**の
役割であり、[branch-protection.md](branch-protection.md)で設定する。本ステップの時点では
まだブランチ保護は未設定であることに注意。
