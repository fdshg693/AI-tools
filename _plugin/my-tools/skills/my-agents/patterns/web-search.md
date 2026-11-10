---
name: web-search
description: Microsoft/Azure公式ドキュメントに限らない一般的なWeb検索が必要で、検索結果をAIエージェントに要約・統合させた回答が欲しい場合に使う。公式ドキュメントに絞りたい場合は`ms-learn-research`パターンを使う。
---

# Webトピック調査パターン: `tavily-agent`

`agents/tavily_agent.yaml`(`tavily-agent`)は、Tavily経由のWeb検索(`tavily_search`)と
本文抽出(`tavily_extract`)をツールとして持つ既存エージェント。新規にエージェントYAMLを
作らず、そのまま`run`に渡せばよい。

```bash
uv run my-agents run tavily-agent --prompt "<調べたいこと>"
```

例:

```bash
uv run my-agents run tavily-agent --prompt "LangChainのcreate_agentとAgentExecutorの違いを教えて"
```

## 挙動

- システムプロンプトにより、推測ではなく`tavily_search`/`tavily_extract`の結果を根拠に
  日本語で回答し、参照ページのタイトルとURLを含めるよう指示されている
- 実行には`tools/my-agents/.env`の`TAVILY_API_KEY`が必要(未設定時のエラー対応は
  このスキルの対象外。`my-agents`スキル本体の前提条件を参照)

## 使い分け

- **統合された回答文だけ欲しい** (検索→抽出→要約をエージェントに一任したい) →
  このパターン(`tavily-agent`)
- **検索結果やページ本文をファイルとして手元に残したい**、複数URLの一括抽出・
  サイトマップ・クロールなど`tavily-agent`のツールセットを超える操作をしたい →
  `tav-cli`/`tav-lit`スキルを直接使う(`tav search`/`tav extract`等)
