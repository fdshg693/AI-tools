---
name: task-tracker
description: 複数タスクを行き来しながら開発する際に、タスクごとの現状(CURRENT.md)とセッションIDを`.claude/tasks/{task-name}/`に自動追跡する。新規タスクの開始・既存タスクの再開の両方を `/task-tracker <task-name>` の1コマンドで扱う。
disable-model-invocation: true
argument-hint: "<task-name>"
meta:
  tag: []
  requires_repo_tools: skill-tools
  requires_env: none
  dependencies: python3
  requires_install: none
  requires_hooks: task_tracker_session (UserPromptExpansion)
  requires_skills: none
  status: draft
  description: no description
  version: 1.0.3
---

`/task-tracker <task-name>` は、複数タスクを行き来する開発で「このタスクの話はこのファイルにメモする」という人間側のマッピングコストをなくすためのスキル。呼び出すたびに `.claude/tasks/{task-name}/` にセッションIDが自動記録され（フック `task_tracker_session`、`UserPromptExpansion`。正本は `agent-tooling/agent_tooling/adapters/claude/task_tracker_session.py`、配置は `skill-tools hooks install --agent claude task_tracker_session`）、このSKILL本体は同じ場所の `CURRENT.md` を都度更新してタスクの現状を追跡する。

## 1. タスク名（`$0`）の扱い

`$0` をタスク名として扱う。新規タスクでも既存タスクの再開でも同じコマンドを使い、`CURRENT.md` の有無で新規/再開を内部的に判定する（下記2節）。

タスク名はフック `task_tracker_session` と同じ正規表現 `^[A-Za-z0-9][A-Za-z0-9_-]*$` でしか受け付けない（英数字・ハイフン・アンダースコアのみ、先頭は英数字）。

- `$0` が空、またはこの正規表現に合わない場合は、タスクディレクトリの作成やファイル操作を一切行わず、正しいタスク名（kebab-case推奨）での再実行をユーザーに求めて終了する。
- このスキルが展開される直前に上記フックも同じ判定を行っており、不正なタスク名の場合は `additionalContext` で警告が会話に追加されていることがある。その警告が見えている場合はそれに従い、同様にファイル操作を行わずユーザーに再実行を促す。

## 2. 新規 / 再開の判定

`.claude/tasks/{task_name}/CURRENT.md` の存在有無で判定する。

- **存在しない → 新規タスク**: 3節へ
- **存在する → 既存タスクの再開**: 4節へ

## 3. 新規タスクの初期化

1. `${CLAUDE_SKILL_DIR}/templates/CURRENT.md.template` を `.claude/tasks/{task_name}/CURRENT.md` としてコピーする（`.claude/tasks/{task_name}/` がまだ無ければ作成する。ただしフックが直前に作成済みのことが多い）。
2. テンプレート内の `{{task-name}}` を実際のタスク名に置き換える。
3. 「タスク `{task_name}` を新規に開始した」旨を短くユーザーに伝え、これから何に取り組むかをヒアリングする。

## 4. 既存タスクの再開

1. `.claude/tasks/{task_name}/CURRENT.md` を読む。
2. `.claude/tasks/{task_name}/sessions.md` を読み、これまで何回・いつこのタスクが呼ばれたかを把握する（過去の会話本文そのものはここには無い。詳細な経緯を掘り返す必要があるときは6節の `dump_sessions.py` を使う）。
3. `CURRENT.md` からリンクされている関連ファイル（詳細ノートなど）があれば必要に応じて読む。
4. これまでの経緯・現状・次にやることを簡潔に要約してユーザーに提示し、作業を再開する。

## 5. 常設ルール: `CURRENT.md` は常にシンプルなASIS状態を保つ

このタスクのセッション中、`CURRENT.md` は常に「今どういう状態か」だけを表す短いドキュメントに保つ。テンプレートの4セクション（タスク名 / 現状ひとこと / 次にやること / 関連ファイル）から肥大化させないこと。

- 設計比較、詳細な調査ログ、決定の経緯といった複雑な内容は `.claude/tasks/{task_name}/` 内の別ファイル（例: `decisions.md`, `notes.md`）に切り出し、`CURRENT.md` の「関連ファイル」節からリンクする。
- `CURRENT.md` の「現状」「次にやること」は、都度の作業の節目で更新すること（セッション終了時にまとめて更新するのではなく、その場で更新する）。

## 6. 過去セッションのトランスクリプトが必要になったら

`sessions.md` にはセッションIDの一覧しかない。過去のやり取りの本文をGrep検索したくなったら、同梱スクリプトでトランスクリプトをダンプする:

```
python "${CLAUDE_SKILL_DIR}/scripts/dump_sessions.py" {task_name}
```

- `.claude/tasks/{task_name}/sessions.md` に記録された各セッションIDについて、`~/.claude/projects/*/{session_id}.jsonl` を検索し、user/assistantのテキスト本文（tool_use/tool_resultの中身は含めない）を `.claude/tasks/{task_name}/temp/dump_{timestamp}.md` に書き出す。
- 見つからなかったセッションIDは出力ファイル内と標準エラー出力の両方に警告として明示される（サイレントに無視されない）。
- `temp/` はこのリポジトリの `.gitignore` の `temp/` ルールで自動的に除外される。
