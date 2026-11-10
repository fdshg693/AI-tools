# Claude Agent SDK を使った、カスタマイズした Claude 利用 CLI ツール

## 関連スキル

- `claude-plugins\meta\skills\claude-agent-sdk`

## ファイル構成

独立したスクリプトはルート直下に置かず、スクリプトごとにサブフォルダを切る。
新しい種類のスクリプトを足すときも同じ（ルートに `.py` を増やさない）。
各サブフォルダのファイル一覧・実行方法は、そのフォルダの `AGENTS.md` を見る。
複数スクリプトが共有するコードは `util/` に置く（実行エントリではない）。

- `minimal_agent/` — カタログ default モデルに一回限りのクエリを送る最小の動作確認（[`minimal_agent/AGENTS.md`](minimal_agent/AGENTS.md)）
- `todo_runner/` — todo.json / NEXT.md 駆動の自律タスク実行ループ（[`todo_runner/AGENTS.md`](todo_runner/AGENTS.md)）
- `todo_detail_runner/` — 上記に各タスクの `detail` モードと `model` を足した変種（[`todo_detail_runner/AGENTS.md`](todo_detail_runner/AGENTS.md)）
- `util/` — 共有ヘルパー。モデルカタログ [`util/models.json`](util/models.json) と解決ロジック（[`util/AGENTS.md`](util/AGENTS.md)）
- `pyproject.toml` — 共通依存（`claude-agent-sdk`）。各スクリプトはパッケージ化せずファイルとして実行する

## セットアップ

前提: `claude` CLI がインストール・ログイン済みであること（または環境変数 `ANTHROPIC_API_KEY` を設定）。

グローバルPythonにインストールする:

```powershell
python -m pip install claude-agent-sdk
```

動作確認は `python minimal_agent\minimal_agent.py`（詳細は [`minimal_agent/AGENTS.md`](minimal_agent/AGENTS.md)）。

## 参照した公式ドキュメント

- `https://code.claude.com/docs/en/agent-sdk/python` — `query()` は既定で毎回新規セッション、
  `ClaudeAgentOptions`（`system_prompt`, `permission_mode`, `setting_sources` 等）、
  `ResultMessage`（`subtype` / `is_error` / `errors`）
- `https://code.claude.com/docs/en/agent-sdk/sessions` — セッションを継がず
  「必要な情報をアプリ側で保持し新規セッションのプロンプトに注入する」設計
- `https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts` — カスタム
  システムプロンプトの指定方法
- `https://code.claude.com/docs/en/model-config` — モデルエイリアス（`haiku` → `claude-haiku-4-5`）
