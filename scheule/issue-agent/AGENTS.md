# ISSUE駆動 worktreeエージェント

GitHub ISSUEのラベル（`tool:claude-code`必須、`model:<alias>`任意）を検知し、git worktree上でClaude Agent SDKにISSUE対応の作業をさせ、完了したらPRを作成・ISSUEへ結果を返信する仕組み。

## 関連ファイル

- `README.md` — 概要・前提条件・`tools/schedule`への登録手順・停止方法・環境変数一覧・トラブルシュート
- 元の実装プランは完了に伴い削除済み（[.claude/plans/README.md](../../.claude/plans/README.md)の「完了後の後片付け」節参照）。設計判断の要約は本ファイルに集約する

## 前提となる設計方針

- **チェック/worker分離**: `check.py`はラベル検索・認可判定・試行記録管理のみ行う。実際の作業（worktree作成・Claude起動・コミット確認・PR確認・ISSUEコメント・後片付け）は`worker.py`を`python -m issue_agent.worker --issue-number N`としてsubprocessで**同期呼び出し**し、完了を待ってから終了する。
- **1周期=1プロセス、内部でループしない**: `check.py`は`while True`もsleepも持たない。繰り返しは`tools/schedule`（Windowsタスクスケジューラのinterval）に委ねる。非同期detach起動にすると、タスクスケジューラがプロセスツリーを終了させた際にworkerが巻き添えで死ぬリスクや、同一worktreeへの同時操作が起きるリスクがあるため。
- **認可判定**: ラベル`tool:`を最後に付与したユーザー（`gh api repos/{owner}/{repo}/issues/{issue_number}/events`の`labeled`イベントの`actor.login`。複数回付け外しされていれば最後のもの）が`gh api repos/{owner}/{repo}/collaborators`のcollaborator一覧に含まれるかで判定する（issue/PRの`author_association`は使わない。ラベル付与イベントには付与されないため）。
- **隔離はgit worktreeのみ**（Dockerは使わない）。worktreeはリポジトリの**外側**（既定`<repo親>/ai-worktrees/issue-<N>`、`ISSUE_AGENT_WORKTREE_ROOT`で変更可）に配置する。メインの作業ツリー内部に置くと通常のgit操作やこのリポジトリ自身の各種チェックスクリプトが誤って巻き込まれるため。
- **権限設計**: Claude Codeは`permission_mode="bypassPermissions"`で通常のAUTO実行させる。危険コマンド（`gh pr merge`・`git push --force`系・`git push -f`・`git push --force-with-lease`・`git branch -D`）のみ`deny_permissions.json`（`ClaudeAgentOptions.settings`経由で渡す追加settings JSON）の`permissions.deny`で拒否する。`can_use_tool`コールバックは`bypassPermissions`下では完全にシャドーイングされ呼ばれないため使わない（明示的denyルールだけが`bypassPermissions`下でも有効という、SDKが保証する数少ない例外）。
- **PR作成はClaudeに任せるが、成否判定はしない**: commit・`git push`・`gh pr create`まで含めてClaude自身に行わせてよい。ただし成否判定はClaudeの自己申告（最終応答テキスト）を信用せず、`worker.py`が`gh pr list --head <branch>`（`state`指定なし＝open状態のみ）を独立に実行した結果を唯一の根拠とする。commitはあるがPRが見つからない場合は「PR作成の指示に従わなかった」失敗として区別する。
- **ISSUE返信・後片付けの責務**: ISSUEへのコメント投稿・worktreeの後片付けは`worker.py`自身（`_report_and_cleanup()`）が行う。Claudeにはやらせない。コメント投稿・後片付け自体の失敗は個別にログへ残すのみで、実際の作業成否（`result["success"]`）には影響させない。
- **GitHub操作は`gh` CLIをそのまま使う**: 新規のGitHub App/PATは作らない。ホスト上で直接動く前提（Docker越しではない）のため、`tools/sandbox`のようにtokenをClaudeから隔離する必要性が薄い。
- **1 ISSUE = 1回まで**: `AttemptStore`（SQLite、`data/state.db`）が成功/失敗を問わず試行記録を管理する。`check.py`はworker起動前に`record_attempt_start()`を呼び、既に試行済みなら起動しない。誤って打ち切られたISSUEを再試行させたい場合は`python -m issue_agent.attempt_store --reset <issue_number>`。

## ファイル構成

```
tools/issue-agent/
├── README.md / AGENTS.md / CLAUDE.md
├── pyproject.toml
├── scripts/
│   └── check.ps1                   # tools/scheduleから呼ばれる薄いラッパー。issue_agent.checkを1回だけ実行する
├── issue_agent/
│   ├── config.py                    # 環境変数駆動の設定（Config.from_env()）
│   ├── environment.py               # .env読込（load_environment()、各エントリポイントのmain()冒頭から呼ぶ）
│   ├── check.py                     # チェックスクリプト本体（ラベル検索・認可判定・attempt_store管理・worker起動）
│   ├── worker.py                    # CLIエントリポイント。ISSUE取得→dispatch解決→worktree作成→Claude起動→
│   │                                 # commit確認→PR実在確認→ISSUEコメント返信→worktree後片付けを一貫して行う
│   ├── dispatch.py                  # tool:/model:ラベルの解決とツール別ハンドラのdispatchテーブル（現状claude-codeのみ）
│   ├── deny_permissions.json        # bypassPermissions下でも有効な明示的denyルール（危険コマンド拒否）
│   ├── worktree.py                  # ISSUE専用git worktreeの作成・削除ラッパー
│   ├── github_ops.py                # ghコマンドのsubprocessラッパー（ISSUE検索・取得・collaborator確認・PR確認・コメント投稿）
│   └── attempt_store.py             # 試行記録SQLiteストア。--reset/--showの手動操作CLIも兼ねる
└── tests/
    └── test_*.py                    # 各モジュールに対応するユニットテスト
```

## companion skillについて

本ツールはスケジューラから機械的に呼ばれるだけの自動化スクリプトであり、対話的にフラグ・enum値の選択に迷うCLIではないため、[tool-companion-skills](../../../docs/repo-wide/tool-companion-skills.md)が対象とする「使い方スキール併設」の対象には該当しないと判断し、現時点では作らない。将来、手動トリガー用のサブコマンド等を追加して利用実態が変わった場合は再検討する。

## 運用上の注意点

- ISSUE本文はリポジトリ外部の第三者が書ける入力（プロンプトインジェクションの経路になりうる）。`dispatch.py`の`SYSTEM_PROMPT_TEMPLATE`に、ISSUE本文中の指示（認証情報送信・別リポジトリ操作・権限昇格・制約無視等）に従わないよう明示している。この設計を変える場合はプロンプト側の防御も合わせて見直すこと。
- サブエージェントは無効化している（`disallowed_tools=["Agent"]`）。`bypassPermissions`はサブエージェントにも継承され上書きできないため。
- ログは`ISSUE_AGENT_LOG_DIR`（既定`data/logs/`、gitignore対象）配下。issueごとのログ（`issue-<N>-<開始時刻>.log`）は`worker.py`サブプロセスの標準出力/標準エラーを丸ごと保存したもので、失敗調査は必ずここを見る。
- 試行記録DBは`ISSUE_AGENT_STATE_DB_PATH`（既定`data/state.db`、gitignore対象）。
- worktreeはPR作成成功時のみ自動削除される。失敗時は調査用に保持されるため、放置すると`ai-worktrees/`配下に残存物が増える。定期的に`git worktree list`で確認し、不要なものは`git worktree remove --force <path>`で手動削除する。
