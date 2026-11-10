# Cursor SDK wrapper

## 概要

`main.py` は、Cursor Python SDK (`cursor-sdk`) を使った **2フェーズのマルチエージェント実行** ラッパーです。

- **フェーズ1（プランナー）**: ユーザーの目標を受け取り、タスク遂行に必要なサブエージェント（モデル・システムプロンプトなど）と実行計画（引き継ぎプロンプト）を設計する。サブエージェントの定義は、モデル出力のパースではなく **カスタムツール実行** で Python 側の状態に登録する（`register_subagent` / `set_handoff_prompt`）。これにより定義はスキーマ検証され、出力フォーマットの揺れに強くなる。
- **フェーズ2（実行）**: フェーズ1で登録されたサブエージェントを inline の `AgentDefinition` として紐づけた **新しいエージェント** を作成し、引き継ぎプロンプトを送って実行する。実行エージェントは必要に応じて `Agent` ツール経由でサブエージェントを起動する。

既定のモデルは `grok-4.5-medium`。利用可能モデル一覧を取得し、現行ID `cursor-grok-4.5-medium` にも解決する。`cursor-sdk-bridge` を起動し `CursorClient` で接続する（Windows版SDKの自動ブリッジ起動の問題を避けるため、ブリッジはスクリプト側で管理）。`CURSOR_API_KEY` は `tools/cursor-wrapper/.env` から読み込み、環境変数が既に設定されていればそちらを優先する。キーはソースコードやログに出さない。

## SDKの使い方

SDKのAPI・実践パターンは `cursor-plugins/meta/skills/cursor-sdk-use/SKILL.md`（同梱の `custom-tools.md` / `subagents.md`）を確認すること。実装前に公式ドキュメント（`cursor-docs` スキル）で最新を確認する。

## 実行

cursor-sdk はルートの uv workspace メンバー（`tools/cursor-wrapper`）としてインストール済み。`CURSOR_API_KEY` は `tools/cursor-wrapper/.env` から読み込む。

```powershell
uv run python tools/cursor-wrapper/main.py
uv run python tools/cursor-wrapper/main.py "このリポジトリの目的を1文で説明し、補強用のサンプルコードを1つ示してください"
uv run python tools/cursor-wrapper/main.py "..." --model grok-4.5-medium
```

初回は `uv sync` で依存（`cursor-sdk`）を共有 venvへ解決すること。

## 関連ファイル

コードの編集・作成・デバッグ時は必ず以下のファイルを参照してください。

- `cursor-plugins/meta/skills/cursor-sdk-use/`
  - Cursor SDK のドキュメントを Markdown 形式でまとめたものです。特に `custom-tools.md`（カスタムツール）と `subagents.md`（サブエージェント / `AgentDefinition`）を参照してください。
