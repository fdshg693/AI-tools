# tools/

`tools/` は1ツール1ディレクトリのまま置く。このファイルは役割で引く索引であり、使い方は書かない。リンク先の README（無いディレクトリは AGENTS.md）を読む。

公開する CLI のインストールパス（`uv tool install --editable tools/<name>` など）と [`repo-tools.yaml`](../repo-tools.yaml) の `path` は、この平坦な配置が契約である。方針は [tools-directory-layout](../docs/repo-wide/tools-directory-layout.md)。

## リポジトリ内部

- [internal](internal/AGENTS.md) — カタログ生成、スキル meta、pre-commit
- [infra](infra/AGENTS.md) — インフラ利用ツール。[ai-logs](infra/ai-logs/README.md)

## 配布する CLI

[`repo-tools.yaml`](../repo-tools.yaml) に載っているツール。`my-agents` と `interactive-cli-wrapper` は下の区分に置く。

- [agents-rules](agents-rules/README.md)
- [aim](aim/README.md)
- [aim2](aim2/README.md)
- [awsdocs](awsdocs/README.md)
- [ctx7](ctx7/README.md)
- [gdevdocs](gdevdocs/README.md)
- [grepapp](grepapp/README.md)
- [linear-cli](linear-cli/README.md)
- [mslearn](mslearn/README.md)
- [ona-run](ona-run/README.md)
- [pyinspect](pyinspect/README.md)
- [skill-tools](skill-tools/README.md)
- [tav-cli](tav-cli/README.md)（キーは `tav`）
- [textgraph](textgraph/README.md)
- [vscode-profiles](vscode-profiles/README.md)

`repo-tools.yaml` には載せず、関連ツールとして1段まとめている既存のグループ:

- [openrouter](openrouter/README.md) — [model-list](openrouter/model-list/README.md)、[model-select](openrouter/model-select/README.md)

## エージェント起動の実験

- [my-agents](my-agents/AGENTS.md) — `repo-tools.yaml` に登録済み
- [sandbox](sandbox/README.md)
- [scheule/ai-schedule](scheule/ai-schedule/README.md)
- [scheule/issue-agent](scheule/issue-agent/README.md)

## ラッパー

`tools/wrappers/` へは移さない。

- [claude-wrapper](claude-wrapper/AGENTS.md)
- [cline-wrapper](cline-wrapper/AGENTS.md)
- [codex-wrapper](codex-wrapper/AGENTS.md)
- [copilot-wrapper](copilot-wrapper/AGENTS.md)
- [cursor-wrapper](cursor-wrapper/AGENTS.md)
- [interactive-cli-wrapper](interactive-cli-wrapper/README.md) — `repo-tools.yaml` のキーは `icw`
