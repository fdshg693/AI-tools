# GitHub ISSUE駆動 worktreeエージェント

GitHub ISSUEにラベル（`tool:claude-code`必須、`model:<alias>`任意）を付けると、`tools/schedule`から定期的に呼ばれるチェックスクリプトがそれを検知し、git worktree上でClaude Agent SDKを起動して実装からPR作成・ISSUE返信までを自動化する仕組み。

## 概要

`tools/sandbox`（Dockerサンドボックス版）のラベル駆動・ISSUE返信までの自動化という思想を、Dockerを使わずgit worktreeによる隔離だけで軽量に実現したもの。隔離範囲を「worktreeで作業ディレクトリをこのブランチに限定する」ことと、危険コマンド（`gh pr merge`・`git push --force`系・`git branch -D`）の明示的拒否だけに絞っている。

設計方針・ファイル構成・運用上の注意点は[AGENTS.md](AGENTS.md)を参照。

## 実装後の使い方

### 前提条件（初回のみ）

1. `gh` CLIでログイン済みであること（`gh auth status`で確認）。ログインアカウントは対象リポジトリのcollaboratorである必要がある（ラベル付与者の認可判定の照合先が`gh api repos/{owner}/{repo}/collaborators`のため、`gh`自身のトークンの権限とは別に、認可対象ユーザー側の権限も要件になる）。
2. `ANTHROPIC_API_KEY`環境変数を設定する（`claude_agent_sdk`が使用）。環境変数として直接exportする代わりに`tools/issue-agent/.env`に書いてもよい（`cp .env.example .env`して値を埋める。`.env`は`issue_agent/environment.py`の`load_environment()`が各エントリポイントの`main()`冒頭で自動読み込みする。`override=False`のため既にexport済みの環境変数が優先される）。
3. リポジトリルートで`uv sync`する（ルートの`pyproject.toml`のworkspace memberとして本パッケージが含まれる）。
4. `tools/schedule`にintervalジョブとして登録する（`tools/schedule/config/jobs.yaml`、詳細は[tools/schedule/AGENTS.md](../schedule/AGENTS.md)参照）:

   ```yaml
   jobs:
     - name: issue-agent-check
       enabled: true
       script: C:\path\to\repo\tools\issue-agent\scripts\check.ps1
       schedule:
         type: interval
         minutes: 15
   ```

   ```bash
   cd tools/schedule
   uv run ai-schedule sync config/jobs.yaml
   ```

### 起動方法

`tools/schedule`のintervalジョブが`scripts/check.ps1`経由で`uv run python -m issue_agent.check`を定期実行する。1回の実行で1周期分だけ処理して終了する（常駐プロセスではない）。動作確認のため手動で1周期分だけ実行したい場合:

```bash
uv run python -m issue_agent.check
```

### 停止方法

`tools/schedule/config/jobs.yaml`の該当ジョブを`enabled: false`にして`uv run ai-schedule sync config/jobs.yaml`を実行する（またはジョブ自体を設定ファイルから削除する）。次回起動時は未処理のISSUEから再開する（試行記録は`data/state.db`にSQLiteで永続化されているため、1 ISSUE = 1回までの試行制限は維持される）。

### 環境変数一覧

すべて任意（未設定時は既定値を使う）。`issue_agent/config.py`の`Config.from_env()`参照。
`ANTHROPIC_API_KEY`含め、シェルでexportする代わりに`tools/issue-agent/.env`（`.env.example`参照）に
書いてもよい。

| 環境変数                             | 既定値                                               | 意味                                                                                                                               |
| ------------------------------------ | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `ISSUE_AGENT_OWNER`                  | `fdshg693`                                           | 対象リポジトリのowner                                                                                                              |
| `ISSUE_AGENT_REPO`                   | `AI`                                                 | 対象リポジトリ名                                                                                                                   |
| `ISSUE_AGENT_TOOL_LABELS`            | `tool:claude-code`                                   | 検索対象の`tool:`ラベル一覧（カンマ区切り）                                                                                        |
| `ISSUE_AGENT_SUPPORTED_TOOL_LABELS`  | `tool:claude-code`                                   | 実際にdispatchできる`tool:`ラベル一覧（カンマ区切り）。`tracked`の部分集合で、対応予定だが未実装のラベルを先に検索対象へ加える用途 |
| `ISSUE_AGENT_ALLOWED_LOGINS`         | (未設定＝毎周期`gh api`でcollaborator一覧を動的取得) | 認可対象ログインを固定したい場合のカンマ区切りリスト                                                                               |
| `ISSUE_AGENT_MAX_ISSUES_PER_CYCLE`   | `1`                                                  | 1周期あたりworkerを起動する最大件数                                                                                                |
| `ISSUE_AGENT_WORKER_TIMEOUT_SECONDS` | `1200`                                               | workerサブプロセスのタイムアウト秒数                                                                                               |
| `ISSUE_AGENT_STATE_DB_PATH`          | `data/state.db`                                      | 試行記録SQLiteのパス（相対パスは`tools/issue-agent/`基準）                                                                         |
| `ISSUE_AGENT_LOG_DIR`                | `data/logs`                                          | issueごとのworkerログの出力先（相対パスは`tools/issue-agent/`基準）                                                                |
| `ISSUE_AGENT_MAX_TURNS`              | `40`                                                 | Claude Agent SDK `query()`の`max_turns`                                                                                            |
| `ISSUE_AGENT_WORKTREE_ROOT`          | `<repo親>/ai-worktrees`                              | ISSUE専用git worktreeの配置先ルート                                                                                                |

### 誤って打ち切ったISSUEを再試行させたい場合

```bash
uv run python -m issue_agent.attempt_store --reset <issue_number>
```

### 試行記録・ログの確認方法

```bash
uv run python -m issue_agent.attempt_store --show <issue_number>
```

`log_file`カラムに、そのISSUEを処理したworkerサブプロセスの標準出力/標準エラーをまとめて保存したログファイルのパスが記録されている（`data/logs/issue-<issue_number>-<開始時刻>.log`、gitignore対象）。

### worktreeの後片付け

PR作成に失敗した場合、調査用にworktreeを保持したまま終了する（保持されたパスは上記ログファイルに`logger.info()`で出力される）。不要になったら手動で削除する:

```bash
git worktree remove --force <path>
```

PR作成に成功した場合はworkerが自動的に削除する。
