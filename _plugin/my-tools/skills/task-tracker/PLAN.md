# task-tracker スキル 実装プラン

> **2026-09 追記**: フックの配置・登録方式は変わった。`.claude/hooks/` と hooks_manager（`hooks.yml` / sync / reflect）は廃止され、フック本体の正本は `agent-compat/agent-tooling/agent_tooling/adapters/claude/task_tracker_session.py`（メタデータは `agent-compat/agent-tooling/agent_tooling/hooks/scenarios/task_tracker_session/hook.yaml`）、配置・登録は `skill-tools hooks install --agent claude task_tracker_session`（このリポジトリではルートの `just hooks-install`）で行う。経緯は [hook-distribution](../../../../../maintenance/docs/hook-distribution.md)。以下は実装当時のプランとして残す。

## 目的

複数タスクを行き来しながら開発する際、「このタスクの話はこのファイルにメモする」という人間側のマッピングコストをなくす。
`/task-tracker <task-name>` で呼び出すたびに、そのタスク専用ディレクトリにセッションIDが自動記録され、AIエージェントは同じ場所の `CURRENT.md` を都度更新することでタスクの現状を追跡する。過去のセッション内容が必要になったら、同梱スクリプトでトランスクリプトをGrep可能な形でダンプできる。

## 呼び出し形式（確定）

```
/task-tracker <task-name>
```

`$0`（= `$ARGUMENTS[0]`）がタスク名。新規タスクでも既存タスクの再開でも同じコマンドを使い、`CURRENT.md` の有無で内部的に新規/再開を判定する。
（当初「ARGUMENTS[1]」という指定だったが、ユーザーに確認したところ言い間違いで `ARGUMENTS[0]` 1本で確定）

## 全体構成

```
tools/_plugin/my-tools/skills/task-tracker/
├── SKILL.md                       # エントリポイント（disable-model-invocation: true）
├── PLAN.md                        # 本ファイル
├── memo/
│   ├── decisions.md               # 設計判断とその理由（要ユーザー確認事項を含む）
│   └── hook-mechanism-notes.md    # フック方式・トランスクリプト所在の技術調査メモ
├── templates/
│   └── CURRENT.md.template        # 新規タスク作成時に複製するテンプレート
└── scripts/
    └── dump_sessions.py           # 過去セッションのトランスクリプトをtempフォルダにダンプ

.claude/hooks/
└── task_tracker_session.py        # 本体フック本体。このリポジトリの既存運用に従いここに置く
                                    # （理由はdecisions.md参照。skill frontmatter内には置かない）

.claude/tasks/{task-name}/         # 実行時に生成される、タスクごとの作業ディレクトリ
├── CURRENT.md                     # ASISな現状サマリ（agentが都度編集）
├── sessions.md                    # フックが自動追記するセッションID一覧
├── (任意の詳細ノートファイル群)     # CURRENT.mdから複雑な内容を切り出したもの
└── temp/                          # dump_sessions.pyの出力先（.gitignoreの`temp/`ルールで自動除外）
```

## 実装ステップ

### ステップ1: フックスクリプト `.claude/hooks/task_tracker_session.py`

- 契約: `event: UserPromptExpansion`, `matcher: task-tracker`
- stdin JSON（`session_id`, `command_name`, `command_args`, `expansion_type` 等）を受け取る
- `command_args` の先頭トークンをタスク名として抽出し、`^[A-Za-z0-9][A-Za-z0-9_-]*$` でサニタイズ
  - 不正/空なら **ブロックしない**（exit 0）が、`hookSpecificOutput.additionalContext` で警告を返しClaude/ユーザーに気付かせる
- 正常なら `.claude/tasks/{task_name}/` を作成（なければ）、`sessions.md` に `- {ISO8601 timestamp} {session_id}` を追記（ファイルがなければヘッダ付きで新規作成）
- 同一 `session_id` が直前の行と同じなら追記しない（同一セッション内で複数回呼んだ場合の重複防止）
- 既存フック（`block_large_read.py` 等）のUTF-8 stdio対策・`_hook_log.py` によるログ仕込みパターンを踏襲する

### ステップ2: hooks_manager経由での登録

- `.claude/scripts` で `just sync` → `hooks.yml` に `enabled: false` で追加されることを確認
- `enabled: true` に変更 → `just reflect` → `.claude/settings.json` に反映
- 動作確認: `echo '{"session_id":"test123","command_name":"task-tracker","command_args":"my-feature","expansion_type":"slash_command"}' | python task_tracker_session.py` を手元で実行し、`.claude/tasks/my-feature/sessions.md` が生成されることを確認

### ステップ3: `SKILL.md` 作成

- frontmatter: `name: task-tracker`, `description`（トリガー: 複数タスクを行き来する開発でタスクごとにセッション・現状を記録したい、等を明記）, `disable-model-invocation: true`（副作用がありタイミングをユーザーが握るべきため）, `argument-hint: "<task-name>"`
- 本文に書く内容:
  1. `$0` をタスク名として扱う（フックと同じサニタイズルールを明記し、フックが弾いた場合の扱いも書く）
  2. `.claude/tasks/{task_name}/CURRENT.md` の有無で新規作成/再開を判定
  3. 新規時: `templates/CURRENT.md.template` を複製して初期化
  4. 再開時: `CURRENT.md` と `sessions.md` を読み、これまでの経緯を要約してユーザーに提示
  5. **常設ルールとして**: セッション中、`CURRENT.md` は常にシンプルなASIS状態を保つ。複雑な内容（設計比較・詳細ログ・調査メモ等）は同ディレクトリ内の別ファイルに切り出し、`CURRENT.md` からリンクする
  6. `scripts/dump_sessions.py` の使い方（過去のやり取りをGrep検索したくなったら実行する）を明記

### ステップ4: `templates/CURRENT.md.template` 作成

最小限のセクションのみ（タスク名 / 現状ひとこと / 次にやること / 関連ファイルへのリンク）。肥大化させない。

### ステップ5: `scripts/dump_sessions.py` 作成

- 入力: タスク名（位置引数）
- `.claude/tasks/{task_name}/sessions.md` からセッションIDのリストを読み取る
- `~/.claude/projects/*/{session_id}.jsonl` をglobして該当トランスクリプトを探す
  - ドライブレターの大小文字ゆれ（`c--CodeRoot-AI` / `C--CodeRoot-AI-*` 等）に対応すること（`claude-code-debugging`スキルの実地検証メモに準拠、詳細はmemo/hook-mechanism-notes.md）
- 見つかったjsonlから会話本文（user/assistantのテキスト中心。巨大なtool_use結果はそのまま埋め込まない）を抽出し、`.claude/tasks/{task_name}/temp/dump_{timestamp}.md` に書き出す
- 見つからなかった `session_id` は出力に警告として明示する（サイレントに無視しない）
- 標準ライブラリのみで完結させ、スキル単体で自己完結させる（`claude-code-debugging/scripts/extract_log.py` への直接依存はしない。理由はdecisions.md参照）

### ステップ6: .gitignore方針の適用

- `temp/` は既存の `.gitignore` ルール（4行目 `temp/`）で自動的に除外される
- `sessions.md` の扱いは要確認（decisions.md参照）

## 読むべきファイル・実行推奨Grep（実装直前に再確認）

- 既存hookの書式踏襲: 当時の `.claude/hooks/block_large_read.py`, `.claude/hooks/_hook_log.py`（現在は `agent-compat/agent-tooling/agent_tooling/adapters/claude/` と `adapters/claude/common/`）
- hooks_manager運用ルール: 当時の `.claude/scripts/AGENTS.md`, `.claude/scripts/hooks_manager.py`（廃止済み。現在は [hook-distribution](../../../../../maintenance/docs/hook-distribution.md)）
- `UserPromptExpansion` の最新入出力スキーマ: `skills/plugins/cc-knowledge/skills/claude-code-docs/output/llms-full.txt` 内 `### UserPromptExpansion` セクション（バージョン差異があり得るので実装直前に再取得推奨。`claude-code-docs`スキル経由で最新化できる）
- セッショントランスクリプトの所在・形式: [skills/plugins/cc-knowledge/skills/claude-code-debugging/logs-and-settings.md](../../../../../skills/plugins/cc-knowledge/skills/claude-code-debugging/logs-and-settings.md)、参考実装 [skills/plugins/cc-knowledge/skills/claude-code-debugging/scripts/extract_log.py](../../../../../skills/plugins/cc-knowledge/skills/claude-code-debugging/scripts/extract_log.py)

## 決定事項・注意点

詳細と理由は [memo/decisions.md](memo/decisions.md) に記載。要点のみ:

1. 呼び出し形式は `/task-tracker <task-name>` 一本（ユーザー確認済み）
2. **フック本体はskill frontmatterではなく `.claude/hooks/` に置き、既存のhooks_manager経由でsettings.jsonへ反映する**（ユーザーの当初要望「スキル内にフックを定義」から変更。理由と代替案はdecisions.md、要ユーザー確認）
3. `sessions.md`・`CURRENT.md` それぞれをgit管理対象にするかは要確認（decisions.md）
4. タスク名のサニタイズルールはフック側とSKILL.md本文側で一致させる
5. `dump_sessions.py` は既存の`extract_log.py`を呼び出さず自己完結の最小実装にする

## オープンクエスチョン（実装着手前にユーザーに確認したいこと）

- [ ] フック設置場所: `.claude/hooks/`配置でよいか、それとも本当にskill frontmatterの`hooks`フィールドを使いたいか（後者を選ぶ場合、初回呼び出し時の発火タイミングを実地検証する追加ステップが必要）
- [ ] gitignore方針: `sessions.md`（セッションIDはこのマシン固有で他環境では無意味）と`CURRENT.md`（チームで共有する価値がある可能性）の扱い
- [ ] `dump_sessions.py`の出力範囲: user/assistantのテキストだけで十分か、tool_use/tool_resultの一部も欲しいか

## `.claude/rules` 更新ポイント

今回はこのリポジトリの既存ルール（`.claude/hooks/AGENTS.md`, `.claude/scripts/AGENTS.md`）に従うだけなので、新規ルールファイルの追加・既存ルールの変更は不要。`.claude/rules/skill-publication.md`は`skills-site/**`限定のスコープでありこのタスクには無関係。
