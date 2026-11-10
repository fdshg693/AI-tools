---
name: my-agents
description: YAML定義のLangchainエージェントを実行・一覧表示・新規作成する `my-agents` CLIの使い方を説明する。カスタムエージェントにプロンプトを投げて答えさせたい、既存のエージェント設定YAMLを確認したい、使えるツールを確認した上で新しいエージェント設定YAMLを作りたい場合に使う。

# 前提条件: リポジトリルートで`uv sync`済みであること（`uv run my-agents ...`で実行）。
# グローバルCLIとして使う場合は`uv tool install --editable tools/my-agents`でも可。
# いずれの場合も`tools/my-agents/.env`（`.env.example`をコピー）に`OPENAI_API_KEY`が
# 設定済みであること。このスキルはインストール・セットアップは一切行わない。
# このスキルの設計意図・前提条件の背景は同階層のREADME.md参照（人間のメンテナ向け）
meta:
  tag: []
  requires_repo_tools: tools/my-agents, tools/mslearn
  requires_env: OPENAI_API_KEY
  dependencies: none
  requires_install: uv sync
  requires_hooks: none
  requires_skills: ms-learn
  status: stable
  description: no description
  version: 1.0.4
---

## エントリポイント: `my-agents` コマンド

```!
uv run my-agents --help
```

未インストール・`OPENAI_API_KEY`未設定などのエラーが出た場合はこのスキルでは対処しない。
ユーザーに `tools/my-agents/README.md` のセットアップ手順（`uv sync`、`.env` への
`OPENAI_API_KEY`設定）を案内する。

## 具体的な利用パターン（`patterns/`）

既存エージェントを使った具体的な利用パターンを`patterns/`配下にファイル単位で用意している。
以下は動的コンテキスト注入（` ```! `ブロック）により`patterns/`配下のファイル一覧と
各`description`（いつ使うか）を実行時に列挙したもの。該当しそうなパターンがあれば、
まずそのファイルを読んでから実行に進む。

```!
python "${CLAUDE_SKILL_DIR}/scripts/list_patterns.py"
```

## 最初に見るべき判断フロー

```markdown
1. 使いたいエージェント設定YAMLがどれか分かっているか?
   Yes -> 3へ
   No -> `my-agents list-agents` で agents/ 配下の既存エージェント一覧
   (name / model / tools) を確認する

2. 既存のどのエージェントも用途に合わない場合
   -> `my-agents list-tools` で使えるツール名(TOOL_REGISTRYのキー)を確認したうえで
   `my-agents new-agent <name> --system-prompt "..." --tool <tool> ...` で
   新しいエージェント設定YAMLを生成し、1へ戻る

3. `my-agents run <config.yaml|エージェント名> --prompt "..."` でエージェントを実行し、
   標準出力の応答テキストを使う（1で確認した`name`をそのまま渡してよい）
```

## サブコマンド

| コマンド                                                                                                                            | 用途                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `my-agents run <config.yaml\|エージェント名> [--prompt "..."]`                                                                      | エージェント設定YAML、またはエージェント名(agents/配下のYAMLの`name`と一致するもの)を指定してエージェントを実行する。既存パスとして存在すればそのままYAMLとして扱い、存在しなければ`agents/`配下を`name`一致で探す(name重複時は最初に見つかったものを使う)。`--prompt`省略時は標準入力からプロンプトを読む。応答テキストのみ標準出力に出す。実行ログ（入力・ツール呼び出し・最終回答）は `tools/my-agents/logs/` に時刻昇順ファイル名で書き、パスを stderr に出す。 |
| `my-agents list-agents`                                                                                                             | `agents/`配下のエージェント設定YAML一覧を`name`/`model`/`tools`付きで表示する。                                                                                                                                                                                                                                                                                                                                                                                     |
| `my-agents list-tools`                                                                                                              | 使用可能なツール(`TOOL_REGISTRY`)の一覧を`名前: 説明`形式で表示する。                                                                                                                                                                                                                                                                                                                                                                                               |
| `my-agents new-agent <name> --system-prompt "..." [--model <id>] [--tool <name>]... [--base-url <url>] [--output <path>] [--force]` | 新しいエージェント設定YAMLを生成する。既定の出力先は`agents/<name>.yaml`。                                                                                                                                                                                                                                                                                                                                                                                          |
| `my-agents help`                                                                                                                    | コマンド一覧・ヘルプを表示する(`--help`と同等)。                                                                                                                                                                                                                                                                                                                                                                                                                    |

## エージェント設定YAMLのフォーマット

```yaml
name: time-agent # エージェント名(表示用)
model: gpt-5.6-luna # OpenAIのモデルID(略記表は無い。IDをそのまま書く)
system_prompt: | # システムプロンプト
  あなたは現在時刻を答えるアシスタントです。
tools: # my-agents list-tools のキーを列挙
  - get_time
base_url: null # 省略可。OpenAI互換の別APIを使う場合のみ指定
```

## 注意点

- `run`は`--prompt`か標準入力のどちらか一方が必須。両方省略するとエラーメッセージを
  stderrに出して終了コード`1`で終わる。
- `run <arg>`はまず既存パスとして解決を試み、無ければ`agents/`配下のYAMLを`name`一致で
  探す。どちらにも該当しなければエラー終了(`1`)。
- `new-agent`の`--tool`に`list-tools`にない名前を渡すとエラー終了(`1`)。
  出力先が既に存在する場合も`--force`を付けないとエラー終了(`1`)。
- モデルIDはOpenAIのモデルID文字列(例: `gpt-5.6-luna`,`gpt-5.6-terra`)をそのまま`--model`または設定YAMLの`model`に書く。
- OpenAI互換の別APIに切り替えたい場合は、設定YAMLの`base_url`(または`new-agent`の`--base-url`)にエンドポイントを指定する。
- `run`は例外発生時にエラーメッセージをstderrに出し、終了コード`1`で終わる
  (LangChain/OpenAI側のエラーも含めそのまま伝播する)。
