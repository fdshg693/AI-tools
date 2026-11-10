# gdevdocs — Google Developer Knowledge MCP の fastmcp ラッパー

**関連スキル: `claude-plugins/my-tools/skills/gdev-docs`**

Google の **Developer Knowledge MCP**（`https://developerknowledge.googleapis.com/mcp`）を、
Python の `fastmcp` クライアントで叩く CLI。GCP と Google Workspace の開発者ドキュメントは
同じコーパスに入っている。クラウド資源の操作はしない。

[`tools/awsdocs`](../awsdocs/README.md) と同じく、`search` / `fetch` / `answer` は1呼び出しにつき
1フォルダへ結果を書き、標準出力には `index.md` のパスだけを出す。

## 前提条件

- Python 3.11+ / uv
- `fastmcp`（下記のインストールで入る）
- API キー。環境変数 `GDEVDOCS_API_KEY`、またはグローバル設定の `api_key`
- キーを発行した Google Cloud プロジェクトで Developer Knowledge API
  （`developerknowledge.googleapis.com`）を有効にしてあること

キーはヘッダ `X-Goog-Api-Key` に載せる。URL のクエリには付けない。
リポジトリルートの `.env` は読まない。プロジェクト設定 `.gdevdocs.toml` に `api_key` を書くと
エラーになる（コミットされうるため）。

## インストール

リポジトリルートで:

```bash
uv tool install --editable tools/gdevdocs
```

## 設定

優先順は、プロセス環境変数、cwd から git ルートまでにある最も近い `.gdevdocs.toml`、
グローバル設定、コード内の既定値。空の環境変数も「設定済み」で、下の層では上書きしない。

| キー         | 環境変数                  | 既定                                            |
| ------------ | ------------------------- | ----------------------------------------------- |
| `api_key`    | `GDEVDOCS_API_KEY`        | なし（必須。グローバル設定のみ）                |
| `output_dir` | `GDEVDOCS_MCP_OUTPUT_DIR` | `temp/gdevdocs_mcp`                             |
| `endpoint`   | `GDEVDOCS_MCP_ENDPOINT`   | `https://developerknowledge.googleapis.com/mcp` |

グローバル設定の場所は `$GDEVDOCS_CONFIG_HOME/config.toml`、なければ
`$XDG_CONFIG_HOME/gdevdocs/config.toml`、なければ `~/.config/gdevdocs/config.toml`
（Windows でも `%USERPROFILE%\.config\gdevdocs\config.toml`）。

相対パスの `output_dir` は、プロジェクト設定に書いたときはそのファイルのディレクトリ基準、
それ以外（環境変数・グローバル設定・既定値）は cwd の git ルート基準。絶対パスと `~` はそのまま。

記入例は [`config.example.toml`](config.example.toml)。今効いている値は `gdevdocs config`
（API キーの値は出さず、有無だけ）。

## 使い方

```bash
gdevdocs search "How to create a Cloud Storage bucket"
gdevdocs fetch documents/docs.cloud.google.com/storage/docs/creating-buckets
gdevdocs fetch https://docs.cloud.google.com/storage/docs/creating-buckets
gdevdocs answer "What is the difference between a bucket and an object"
gdevdocs tools
gdevdocs call search_documents --args "{\"query\": \"Cloud Storage bucket\"}"
gdevdocs config
```

| コマンド | MCP ツール         | 出力                                                        |
| -------- | ------------------ | ----------------------------------------------------------- |
| `search` | `search_documents` | フォルダ（1チャンク1ファイル＋`index.md`）                  |
| `fetch`  | `get_documents`    | フォルダ（最大20件。`documents/...` または `https://` URL） |
| `answer` | `answer_query`     | フォルダ（回答と `references` を1ファイル）                 |
| `tools`  | `tools/list`       | 標準出力                                                    |
| `call`   | 任意               | 標準出力（生 JSON）                                         |
| `config` | なし               | 標準出力（設定の出どころ。通信しない）                      |

共通オプション: `--endpoint`、`--timeout`（既定 60 秒）。`--endpoint` は環境変数より上。

`search` の各ファイルには `URL:`（`documents/` を外して `https://` を付けたもの）と `Parent:` を書く。
`fetch` の `URL:` は応答の `uri`。`answer` は `answerText` と `references` を1ファイルに書く。

終了コード: 0 成功 / 1 実行時エラー（キー欠落、接続失敗、429） / 2 引数エラー /
3 ツールの `is_error` / 4 結果 0 件。存在しない文書名は exit 3 で
`Requested document was not found.` が返る（リダイレクトはしない）。

`search` と `fetch` の 429 は 3 秒待って1回だけ再試行する。`answer` は再試行しない
（`AnswerQuery` の既定は 1 日 50 回。429 のときは `search` に落とす）。

## ファイル構成

```text
tools/gdevdocs/
  gdevdocs_cli.py       argparse と終了コード
  gdevdocs_core/
    config.py           定数
    environment.py      レイヤー設定
    client.py           fastmcp 接続と 429
    responses.py        CallToolResult の正規化
    rendering.py        Markdown 化
    output.py           連番フォルダと index.md
  tests/test_output.py  オフライン（ライブ MCP は叩かない）
  config.example.toml
  README.md
  AGENTS.md
  CLAUDE.md
```
