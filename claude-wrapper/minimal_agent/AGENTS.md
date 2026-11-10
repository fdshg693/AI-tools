# minimal_agent — Claude Agent SDK の最小動作確認

[`../util/models.json`](../util/models.json) の default モデルに一回限りのクエリを送り、応答テキストと終了ステータスを表示する。認証は `claude` CLI のログイン、または `ANTHROPIC_API_KEY`。セットアップは親の [`../AGENTS.md`](../AGENTS.md) を参照。

## ファイル

- `minimal_agent.py` — エントリ。`query()` を 1 回呼び、`AssistantMessage` の本文と `ResultMessage.subtype` を出す

## 実行

```powershell
cd tools\claude-wrapper
python minimal_agent\minimal_agent.py
```

期待される出力（応答テキスト + 終了ステータス）:

```text
私はClaudeで、... をサポートするエージェントです。
終了: success
```

使うモデルはカタログの `default`（現状 `haiku`）。許可 id と解決先は [`../util/AGENTS.md`](../util/AGENTS.md)。
