# my-agents — YAML定義のLangchainエージェント

**Langchain スキル: `claude-plugins\topics\skills\langchain-docs\SKILL.md`**
**このCLI利用スキル: `claude-plugins/my-tools/skills/my-agents`**

- ツール（Python関数）はコード内（`my_agents/tools/`）で責務ごとにファイルを分けて定義し、レジストリに登録する
- 各エージェントはYAMLファイル1つに対応し、使用するモデル・システムプロンプト・使用可能なツール名（レジストリのキー）を宣言する
- スキルは `skills/{skill-name}_SKILL.md` に置き、全エージェントに名前・descriptionが渡り、`load_skill` で本文を取得できる
- モデル呼び出しはLangchainの `create_agent`（`langchain.agents`）+ `ChatOpenAI`（OpenAI Responses API）を使用する

## セットアップ（APIキー）

`tools/my-agents/.env`（`.env.example` をコピー）に `OPENAI_API_KEY` を設定する。実行時のカレントディレクトリに依存せず、常にこのファイルを参照する。`tavily_*` ツールを使う場合は `TAVILY_API_KEY` も同じくこの `.env` に設定する（`agent.py` が `build_chat_model` 内で `load_dotenv(ENV_PATH)` し、`os.environ` に載せたものを `tav_core.create_tavily_client()` が読む）。

```bash
cp tools/my-agents/.env.example tools/my-agents/.env
# .env を編集して OPENAI_API_KEY=sk-... / TAVILY_API_KEY=tvly-... を設定
```

OpenAI互換の別APIに切り替えたい場合は、エージェント設定YAMLの `base_url` にエンドポイントを指定する。

## 使い方

リポジトリルートで `uv sync` 済みであること（ルートの `pyproject.toml` のworkspace memberとして本パッケージが含まれる）。

CLIは[Typer](https://typer.tiangolo.com/)製で、以下のサブコマンドを提供する。

```bash
# コマンド一覧・ヘルプを表示
uv run my-agents --help
uv run my-agents help

# エージェントを実行する（引数でプロンプトを渡す）
# 標準出力は最終回答のみ。実行ログのパスは stderr に `log: ...` として出る
uv run my-agents run tools/my-agents/agents/time_agent.yaml --prompt "今何時ですか？"

# 設定YAMLのパスの代わりに、エージェント名(YAML内のname)でも実行できる
# name重複時は agents/ 配下をソートして最初に見つかったものを使う
uv run my-agents run time-agent --prompt "今何時ですか？"

# 標準入力からプロンプトを渡す（--prompt 省略時は stdin を読む）
echo "今何時ですか？" | uv run my-agents run tools/my-agents/agents/time_agent.yaml

# agents/ 配下のエージェント設定YAML一覧を表示する
uv run my-agents list-agents

# 利用可能なツール（TOOL_REGISTRY）一覧を表示する
uv run my-agents list-tools

# name/description/args(引数のJSON Schema)をYAMLで出力する(--outputで指定パスに書き出し)
uv run my-agents list-tools --format yaml --output tools/my-agents/tools/tools.yaml

# 同じことを justfile 経由で(tools/my-agents/tools/tools.yaml を再生成)
just --justfile tools/my-agents/justfile tools-yaml

# 新しいエージェント設定YAMLを生成する（agents/<name>.yaml に出力）
uv run my-agents new-agent my-new-agent \
  --system-prompt "あなたは..." \
  --model gpt-5.6-luna \
  --tool get_time
```

グローバルCLIとして使う場合は `uv tool install --editable tools/my-agents` でエディタブルインストールする。

## 実行ログ

`my-agents run` のたびに、入力・ツール呼び出し（名前と引数）・最終回答を `tools/my-agents/logs/` 配下へ1ファイル書き出す（ツール結果は含めない）。ファイル名は `YYYYMMDDTHHMMSS_ffffff_<agent>.yaml` で、辞書順＝時刻昇順になる。ログディレクトリは gitignore 対象。

## エージェント設定YAMLのフォーマット

````yaml
name: time-agent          # エージェント名（表示用）
model: gpt-5.6-luna        # OpenAIのモデルID（例: gpt-5.6-luna, gpt-5.6-terra）
system_prompt: |            # システムプロンプト
  あなたは現在時刻を答えるアシスタントです。
  ...
tools:                        # my_agents/tools/ の TOOL_REGISTRY のキーを列挙
  - get_time
base_url: null                 # 省略可。OpenAI互換の別APIを使う場合のみ指定
```　

## スキル（`skills/`）

`tools/my-agents/skills/{skill-name}_SKILL.md` にスキルを置く（同階層の別ファイルはスコープ外）。フロントマターの `description` がカタログに使われ、ファイル名の `{skill-name}` がスキル名になる。

あらゆるエージェントのシステムプロンプト末尾に、利用可能なスキル名と description の一覧が自動追記される。本文が必要なら `load_skill` ツールにスキル名を渡す（フロントマターを除いたテキストが返る）。`load_skill` は YAML の `tools:` に書かなくても全エージェントに自動付与される。

```markdown
---
name: example
description: いつこのスキルを使うかの短い説明。
---

# スキル本文

エージェントが load_skill で取得する指示を書く。
```

## 利用可能なツール（`my_agents/tools/`）

| ツール名 | 説明 |
|---|---|
| `get_time` | 指定IANAタイムゾーン（既定 `Asia/Tokyo`）の現在時刻をISO 8601形式で返す |
| `mslearn_search` | Microsoft Learn / Azure公式ドキュメントを検索し、結果(title/content/contentUrl)をJSON文字列で返す |
| `mslearn_code_search` | Microsoft/Azure公式のコードサンプルを検索し、結果をJSON文字列で返す（`language`で言語を絞り込み可） |
| `mslearn_fetch` | Microsoft Learnのページ1件をMarkdown本文として取得する |
| `tavily_search` | TavilyでWeb検索を行い、結果(title/url/content)のリストをJSON文字列で返す（`detail`=`quick`/`balanced`/`max`、`include_domains`/`exclude_domains`でドメイン絞り込み可） |
| `tavily_extract` | 指定URLの本文をTavilyで抽出し、結果リストをJSON文字列で返す（`query`で関連性フォーカス抽出可、`detail`=`quick`/`balanced`/`max`） |
| `load_skill` | スキル名に対応する `skills/{name}_SKILL.md` の本文（フロントマター除く）を返す。全エージェントに自動付与 |

`mslearn_*` は [`tools/mslearn`](../mslearn) パッケージ（`mslearn_core`）をライブラリとして薄くラップしたもの（`my_agents/tools/mslearn_tools.py`）。`tavily_*` は [`tools/tav-cli`](../tav-cli) パッケージ（`tav_core` + `search_topic` / `extract_url_content`）をライブラリとして薄くラップしたもの（`my_agents/tools/tavily_tools.py`）。いずれもCLI版と異なり結果をファイルに書き出さず、そのままツールの戻り値としてエージェントの文脈に返す。

ツールは `my_agents/tools/` 配下に責務ごとにファイルを分けて実装する（例: `time_tools.py`, `mslearn_tools.py`）。新しいツールを追加する場合は、既存ファイルに追記するか新規モジュールを追加して `@tool` 関数を実装し、`my_agents/tools/__init__.py` の `_TOOLS` に登録する。YAML側は登録したツール名を `tools:` に追加するだけで使えるようになる。

## ファイル構成

````

tools/my-agents/
├── README.md # 本ファイル
├── justfile # tools-yaml: tools/tools.yaml を再生成するショートカット
├── pyproject.toml # パッケージ定義 + console script (my-agents)
├── .env.example
├── .env # gitignore対象
├── .gitignore
├── my_agents/
│ ├── **init**.py
│ ├── tools/ # ツールのコード内定義・レジストリ(ファイル毎に責務分割)
│ │ ├── **init**.py # 各モジュールのツールを集約し TOOL_REGISTRY を構築
│ │ ├── time_tools.py # get_time
│ │ ├── mslearn_tools.py # mslearn_search / mslearn_code_search / mslearn_fetch
│ │ ├── tavily_tools.py # tavily_search / tavily_extract
│ │ └── skill_tools.py # load_skill（全エージェントに自動付与）
│ ├── skills.py # skills/ 配下の {name}_SKILL.md の一覧・本文読み込み
│ ├── config.py # エージェント設定YAMLの読み込み(pydantic)
│ ├── agent.py # ChatOpenAI(Responses API) + create_agent の組み立て
│ ├── run_log.py # 実行ログ（入力・ツール呼び出し・最終回答）の書き出し
│ └── cli.py # CLIエントリポイント（Typer製。run/list-agents/list-tools/new-agent/help）
├── agents/
│ └── time_agent.yaml # get_timeツールを使う最小構成のサンプルエージェント
├── skills/ # {skill-name}_SKILL.md を置く（エージェント実行時にカタログ化）
├── logs/ # 実行ログ（gitignore対象。呼び出しごとに1ファイル）
└── tools/
└── tools.yaml # `just tools-yaml`で生成される、TOOL_REGISTRYの機械可読な一覧(name/description/args)

```

```
