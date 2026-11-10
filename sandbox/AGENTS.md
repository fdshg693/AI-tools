# ISSUE駆動 Dockerサンドボックスエージェント

GitHub ISSUEの `@sandbox` メンションをポーリングで検知し、使い捨てDockerコンテナ内でClaude Agent SDKにISSUE対応の作業をさせ、完了したらPRを作成する仕組み。

## 関連ファイル

- `README.md` — 構想の原文（ラフプラン）＋実装後の使い方（前提条件・起動/停止コマンド）
- `CONSIDERATIONS.md` — 構想の実現可能性検討メモ

## 前提となる設計方針

- 対象リポジトリはこのAIリポジトリ専用に固定（`GITHUB_OWNER`/`GITHUB_REPO`環境変数で上書き可能）。
- 実行単位は常駐ポーリングワーカー1プロセス + ISSUEごとに`docker run`で使い捨てコンテナ。1 ISSUE = 1セッション（ステートレス、`tools/claude-wrapper/todo_runner/todo_runner.py`と同じく新規セッションで完全リセットする設計）。
- 完了時のフィードバックは、成功時はPR作成のみ／失敗時のみISSUEにエラーコメント。
- 安全境界はDockerコンテナ＋GitHub App最小権限＋Claude Code組み込みネットワークサンドボックスの三重防御。Bypass Permission自体は安全境界ではないため、これらの多層防御が実効性を持つように各設定（下記「運用上の注意点」参照）を維持すること。
- クラウド移行そのものはスコープ外だが、将来Cloud Run Job / ECS Fargate等へ移行しやすいよう設定は環境変数駆動・Docker Compose構成に閉じ、ホスト固有パスやWindows依存処理は持ち込まない。

## ファイル構成

- `docker/Dockerfile` — Claude Agent SDK実行用イメージ（`python:3.12-slim-bookworm` + git + bubblewrap/socat、非rootユーザー）
- `docker/claude-settings/managed-settings.json` — `/etc/claude-code/managed-settings.json`としてイメージに焼き込むロックダウン設定（`sandbox.network.allowManagedDomainsOnly`等。project設定やSDKオプションでは効かないため、ここでのみ有効）
- `docker/claude-settings/settings.json` — project向けの非セキュリティ設定（`sandbox.filesystem.allowWrite`等）
- `github_app/get_installation_token.py` — GitHub App installation access tokenの取得（JWT RS256署名 → token取得）
- `github_app/git_credential_inject.py` — 取得したトークンをgit remote URLに注入
- `docs/github-app-setup.md` — GitHub App作成手順（画面操作ベース、一度きりの手動セットアップ）
- `docs/branch-protection.md` — `main`ブランチ保護ルールの適用Runbook（`gh api`コマンド、一度きりの手動セットアップ）
- `orchestrator/poller.py` — 常駐ポーリングワーカー本体。`@sandbox`メンションのあるISSUEを検索し、未処理（対応PR未作成）かつメンション実行者が許可対象（`is_mention_authorized()`）のものを`run_agent.run_container()`へ渡す
- `orchestrator/run_agent.py` — ホスト/コンテナ両モードを持つ1ファイル。ホスト側は`docker run`でISSUE専用コンテナを起動し、コンテナ側（`--container-mode`）はclone〜Claude Agent SDK `query()`〜push を行う。コンテナに注入される環境変数の一覧は`run_container()`内の`docker run -e`列挙が正（`docker/.env.example`のような別ファイルは持たない）
- `orchestrator/github_client.py` — GitHub REST/Search APIの薄いラッパー（stdlib `urllib`のみ、PyGithub等は未使用）。ISSUE検索・ISSUE/コメント取得・PR有無確認・コメント投稿・PR作成を提供
- `orchestrator/state.py` — ISSUEごとの試行記録（1 ISSUE = 1回まで、`log_file`パスも保持）をSQLiteで管理する`AttemptStore`。手動リセット用CLI（`python state.py --reset <issue_number>`）・試行記録参照用CLI（`python state.py --show <issue_number>`）も兼ねる
- `orchestrator/logging_setup.py` — ロギング初期化（コンソール + JSON Linesファイルの2ハンドラ、`contextvars`による`issue_number`相関、`TokenRedactionFilter`）。`poller.py`（ホスト常駐）と`run_agent.py`のコンテナモード（軽量版、ファイルハンドラなし）の両方から使う
- `orchestrator/pyproject.toml` / `orchestrator/.env.example` — ホスト側ワーカーの依存定義・環境変数一覧。`poller.py` は起動時に同階層の `.env` を読む（プロセス環境が優先）。コンテナ内の `run_agent.py --container-mode` と `github_app/get_installation_token.py` は `.env` を読まない

## 運用上の注意点

- ネットワーク制御はDockerネットワーク自体ではなくClaude Code組み込みの`sandbox.network.allowedDomains`が主防御。許可ドメインを追加する際は`docker/claude-settings/managed-settings.json`を更新する（`settings.json`ではない。project設定/SDKオプション経由の`allowManagedDomainsOnly`は効かないため）。
- GitHub Appのinstallation access tokenは1時間で失効する。コンテナ起動のたびに`github_app/get_installation_token.py`で新規取得する設計（永続キャッシュしない）。
- Bypass Permission（`permission_mode="bypassPermissions"`）はサブエージェントにも継承され上書きできない。`orchestrator/run_agent.py`では`disallowed_tools=["Agent"]`で明示的に外している。
- ISSUEへの自動対応は成功/失敗を問わず**1 ISSUE = 1回まで**。`orchestrator/state.py`の`AttemptStore`がSQLite（既定`orchestrator/data/state.db`、`SANDBOX_STATE_DB_PATH`で変更可、gitignore対象）で試行記録を管理し、`poller.py`はコンテナ起動前に試行済みかどうかを確認する。一度試行を開始したISSUEは、一時的なインフラ障害による失敗であっても自動では再試行されない。誤って打ち切られたISSUEを再試行させたい場合は`python state.py --reset <issue_number>`で試行記録を削除する。既存の「対応PRの有無」判定は、state.dbが消失・リセットされた場合の保険として重複PR防止の副次チェックのまま残している。
- コンテナ内のClaudeにGitHub tokenを一切触れさせない設計にしている（`orchestrator/run_agent.py`のモジュールdocstring参照）: tokenは環境変数で受け取った直後に`os.environ`から除去し、`git clone`/`git push`は`.git/config`に残らない一時ヘッダー認証にし、`git push`自体もClaudeにはやらせずスクリプト側が`query()`終了後に実行する。ISSUE本文（プロンプトインジェクションの入力経路）からこの設計を変えないこと。成否判定は同様の理由（Claudeの応答に偽の成功シグナルを混入されるリスク）から、コンテナのexit codeを一次情報とし、`SANDBOX_RESULT: `行はエラー内容の補足表示にのみ使う（`orchestrator/run_agent.py`参照）。
- `@sandbox`メンションは誰でも書けるため、`orchestrator/poller.py`の`is_mention_authorized()`が、メンションを実際に書いた投稿者（ISSUE本文またはコメントの投稿者、ISSUE作成者とは限らない）の`author_association`を`SANDBOX_ALLOWED_AUTHOR_ASSOCIATIONS`（既定`OWNER,COLLABORATOR`）と照合し、該当しなければコンテナを起動しない。許可対象を広げる場合はCONTRIBUTOR以下は「write権限を持たない/継続的な関与が保証されない」ユーザーも含む点に注意（詳細: [branch-protection.md](docs/branch-protection.md)と対になる認可ゲート。GitHub Appの権限自体は絞れないため、この判定がアプリケーション層での唯一の防御）。
- `main`への直接pushはGitHub App権限では防げない（Contents:Writeが必須のため）。[docs/branch-protection.md](docs/branch-protection.md)のブランチ保護ルール（`required_pull_request_reviews`）が唯一の防御であり、初回セットアップ時に必ず適用すること。
- ログの置き場所は`SANDBOX_LOG_DIR`（既定`orchestrator/data/logs/`、gitignore対象）。`poller.py`本体のログ（`orchestrator.log`、JSON Lines）は`TimedRotatingFileHandler`で日次ローテーションし、`SANDBOX_LOG_RETENTION_DAYS`（既定14）世代分のみ保持する。ISSUE単位のコンテナ実行ログ（`issues/issue-<N>-<開始時刻>.log`）は`docker run`の標準出力/標準エラーを丸ごと保存したもので、タイムアウト時の部分出力も含む。使い捨てコンテナ内には残らないため、コンテナ内失敗の調査は必ずこのファイルを見る（自動削除されない。`state.py --show <issue_number>`から該当パスを辿れる）。
- `TokenRedactionFilter`（`orchestrator/logging_setup.py`）は、フォーマット後のログメッセージ全文に対する正規表現ベースのtoken伏字化で、全ハンドラ共通の安全網として効く。`run_agent.py`の既存`_redact()`（コマンド引数列だけが対象のピンポイント対策）やtokenを`os.environ`から即除去する設計と併存する追加の多層防御であり、いずれか一方に置き換えるものではない。
