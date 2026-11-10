# サンドボックス環境でのAIコーディングツール利用

AIコーディングツールは便利だが、強力な権限を与えるのは非常に危険。
しかし、権限を制限するのはなかなかコストがかかり、プロジェクト・場面によって様々に変化する。
そこで、サンドボックス環境を立ち上げて、そのなかでAIコーディングツールを動かすことで、権限を制限しつつ、便利さを享受することができる。

## 概要

サンドボックス環境に作業に必要なGithubへのアクセス権限等を最小権限で渡す。
サンドボックス内のツールは自由に使えるようにすることで、権限による危険を回避しつつ、便利さを享受することができる。
必要なAPIキー等は環境変数経由でサンドボックスに注入する、そしてそれらのAPIキーの権限を絞る。

### 前提条件（初回のみ）

1. [docs/github-app-setup.md](docs/github-app-setup.md)に沿ってGitHub Appを作成し、
   対象リポジトリにインストールする（App ID・Installation ID・秘密鍵を控える）。
2. [docs/branch-protection.md](docs/branch-protection.md)に沿って`main`ブランチ保護を
   設定する（GitHub Appによる直接pushを防ぐため。人間オーナーの直接pushは引き続き可能）。
3. Dockerイメージをビルドする。

   ```bash
   docker build -t sandbox-agent:latest -f tools/sandbox/docker/Dockerfile tools/sandbox/docker
   ```

4. `tools/sandbox/orchestrator/.env.example`を`.env`にコピーし、GitHub App認証情報・
   `ANTHROPIC_API_KEY`・`SANDBOX_IMAGE`等を埋める（各変数の意味は`.env.example`内コメント参照）。

### 起動方法

```bash
cd tools/sandbox/orchestrator
uv sync
uv run python poller.py
```

`poller.py` は同階層の `.env` を起動時に読む（すでに export した環境変数が優先）。
`github_app/get_installation_token.py` は `.env` を読まないので、単体実行するときは
プロセス環境へ同じキーを渡す。

常駐プロセスとして`@sandbox`メンション付きのopen issueをポーリングする
（既定60秒間隔、`SANDBOX_POLL_INTERVAL_SECONDS`で変更可）。対象ISSUEを見つけると
使い捨てDockerコンテナを起動してClaude Agent SDKに作業させ、成功時はPRを作成、
失敗時はISSUEにエラーコメントを投稿する。

### 停止方法

`Ctrl+C`でポーリングループを終了する（実行中のコンテナがあれば、そのコンテナの
処理完了・タイムアウトを待ってから終了する）。次回起動時は未処理のISSUEから再開する
（状態は`orchestrator/data/state.db`にSQLiteで永続化されているため、再起動しても
1 ISSUE = 1回までの試行制限は維持される）。

### 誤って打ち切ったISSUEを再試行させたい場合

```bash
cd tools/sandbox/orchestrator
uv run python state.py --reset <issue_number>
```

### ログの確認方法

ログは`SANDBOX_LOG_DIR`（既定`orchestrator/data/logs/`、gitignore対象）配下に2種類ある。

- `orchestrator.log` — `poller.py`本体の構造化ログ（JSON Lines、日次ローテーション、
  `SANDBOX_LOG_RETENTION_DAYS`世代分保持）。コンソールには同内容が人間可読テキストで
  同時出力される。
- `issues/issue-<issue_number>-<開始時刻>.log` — ISSUEごとのコンテナ実行ログ
  （`docker run`の標準出力/標準エラーを丸ごと保存。タイムアウトで打ち切られた場合も
  その時点までの部分出力が残る）。使い捨てコンテナ内には残らないため、失敗調査は
  必ずこのファイルを見る。

該当ISSUEのログファイルパスは`state.py --show`で試行記録ごと確認できる:

```bash
cd tools/sandbox/orchestrator
uv run python state.py --show <issue_number>
```

リアルタイムで追いたい場合は該当ファイルを`tail -f`する:

```bash
tail -f tools/sandbox/orchestrator/data/logs/issues/issue-123-*.log
```
