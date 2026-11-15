# tools/

`tools/` は 1 ツール 1 ディレクトリ。性質がはっきりしたツールは 1 段のカテゴリフォルダ（`tools/<category>/<name>`）にまとめ、それ以外は `tools/<name>` に置く。このファイルは役割で引く索引であり、使い方は書かない。リンク先の README（無いディレクトリは AGENTS.md）を読む。

公開する CLI のインストールパス（`uv tool install --editable tools/llm/aim` など）と [`repo-tools.yaml`](../registry/repo-tools.yaml) の `path` は、この配置が契約である。カテゴリの決め方と新しいツールの振り分けは [tools-directory-layout](../maintenance/docs/tools-directory-layout.md)。

## 付属スキル

- [_plugin/my-tools](_plugin/my-tools/README.md) — このディレクトリの CLI を前提にした使い方スキルの Claude Code プラグイン（`my-tools`）。ツールではないので `_` 始まりにしている

## カテゴリ

### llm/ — AI モデル・エージェントを呼び出す

- [aim](llm/aim/README.md)
- [aim2](llm/aim2/README.md)
- [my-agents](llm/my-agents/AGENTS.md) — YAML 定義の LangChain エージェント

### coding-agent/ — AI コーディングエージェントの運用

- [agents-rules](coding-agent/agents-rules/README.md)
- [ai-usage](coding-agent/ai-usage/README.md) — AI コーディングツールの使用量表示（個人用 CLI、`repo-tools.yaml` 未登録）

### web-research/ — Web 調査

- [awsdocs](web-research/awsdocs/README.md)
- [ctx7](web-research/ctx7/README.md)
- [gdevdocs](web-research/gdevdocs/README.md)
- [grepapp](web-research/grepapp/README.md)
- [mslearn](web-research/mslearn/README.md)
- [tav-cli](web-research/tav-cli/README.md)（`repo-tools.yaml` のキーは `tav`）

### openrouter/ — OpenRouter のモデル一覧・選定の補助

`repo-tools.yaml` には載せていない。

- [openrouter](openrouter/README.md) — [model-list](openrouter/model-list/README.md)、[model-select](openrouter/model-select/README.md)

## カテゴリに入れていないツール

- [interactive-cli-wrapper](interactive-cli-wrapper/README.md) — `repo-tools.yaml` のキーは `icw`
- [linear-cli](linear-cli/README.md)
- [pyinspect](pyinspect/README.md)
- [skill-tools](skill-tools/README.md)
- [textgraph](textgraph/README.md)
- [vscode-profiles](vscode-profiles/README.md)
- [infra](infra/AGENTS.md) — インフラ利用ツール。[ai-logs](infra/ai-logs/README.md)

`ai-usage`・`openrouter`・`infra` 以外は [`repo-tools.yaml`](../registry/repo-tools.yaml) に登録済み。

## 他の置き場所

- カタログ生成・スキル meta・pre-commit などリポジトリ保守用のスクリプトは [maintenance/scripts](../maintenance/scripts/AGENTS.md) にある（tools/ ではない）。
- AI コーディングツールの CLI ラッパー（`claude-wrapper` など）と、sandbox・schedule のようなエージェントの自動実行は、カスタマイズして使うワークフローとして [workflow/](../workflow/README.md) サブモジュールに置く。
