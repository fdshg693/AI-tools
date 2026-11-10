---
name: ms-learn-research
description: Microsoft/Azure公式ドキュメントに基づいた回答が必要で、検索・コードサンプル検索・ページ取得をAIエージェントに一任して要約させたい場合に使う。公式ドキュメント以外も含む一般的なWeb検索には`web-search`パターンを使う。
---

# MS Learn調査パターン: `mslearn-agent`

`agents/mslearn_agent.yaml`(`mslearn-agent`)は、Microsoft Learn / Azure公式ドキュメントの
検索(`mslearn_search`)・コードサンプル検索(`mslearn_code_search`)・ページ取得
(`mslearn_fetch`)をツールとして持つ既存エージェント。新規にエージェントYAMLを作らず、
そのまま`run`に渡せばよい。

```bash
uv run my-agents run mslearn-agent --prompt "<調べたいこと>"
```

例:

```bash
uv run my-agents run mslearn-agent --prompt "Azure Functions Python v2 プログラミングモデルのタイムアウト設定方法"
```

## 挙動

- システムプロンプトにより、推測ではなく`mslearn_search`/`mslearn_code_search`/
  `mslearn_fetch`の結果を根拠に日本語で回答し、参照ページのタイトルとURLを含めるよう
  指示されている
- Microsoft Learn MCPは公開エンドポイントのため認証不要(`ms-learn`スキルと同じ)

## 使い分け

- **統合された回答文だけ欲しい** (検索→本文取得→要約をエージェントに一任したい) →
  このパターン(`mslearn-agent`)
- **検索結果一覧やページ全文をファイルとして手元に残したい**(`index.md`付きの
  結果フォルダが欲しい等)、`mslearn-agent`のツールセットを超える操作
  (`mslearn tools`/`mslearn call`での任意ツール呼び出し等)をしたい →
  `ms-learn`スキルを直接使う(`mslearn search`/`mslearn fetch`等)
