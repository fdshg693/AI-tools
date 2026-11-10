---
name: gdev-docs
description: Search, fetch, and answer from official Google Cloud and Google Workspace developer documentation via the self-built `gdevdocs` CLI, a fastmcp wrapper around the Developer Knowledge MCP (https://developerknowledge.googleapis.com/mcp). Use when you need GCP or Workspace developer docs (concepts, APIs, SDKs, configuration, quotas, error explanations). Do not use for general web research (`tav-cli`), Microsoft docs (`ms-learn`), AWS docs (`aws-docs`), operating GCP or Workspace resources, or version-specific client-library APIs (`use-context`).

# 前提条件: `gdevdocs` コマンドが PATH 上にインストール済み
# (`uv tool install --editable tools/gdevdocs`)であり、`GDEVDOCS_API_KEY` が
# 環境変数かグローバル設定で解決できること。このスキルはインストール・API の有効化を
# 一切行わない。公式 Agent Skill（google/skills の retrieving-developer-knowledge）も
# 入れない。設計意図は同階層の README.md（人間のメンテナ向け）。
meta:
  tag: []
  requires_repo_tools: gdevdocs
  requires_env: GDEVDOCS_API_KEY, GDEVDOCS_MCP_OUTPUT_DIR, GDEVDOCS_MCP_ENDPOINT
  dependencies: none
  requires_install: uv tool install --editable tools/gdevdocs
  requires_hooks: none
  requires_skills: none
  status: experimental
  description: GCP と Workspace の開発者向け公式ドキュメントを gdevdocs で引く
  version: 0.1.0
---

## エントリポイント: `gdevdocs` コマンド

```!
gdevdocs --help
```

未インストール、または API キーが解決できないときは、このスキルでは対処しない。
ユーザーに `tools/gdevdocs/README.md` のセットアップ（`uv tool install --editable tools/gdevdocs`、
`GDEVDOCS_API_KEY`、Developer Knowledge API `developerknowledge.googleapis.com` の有効化）を案内する。

キーは環境変数かグローバル設定だけ。プロジェクトの `.gdevdocs.toml` と、リポジトリルートの
`.env` は CLI が読まない。今効いている値の出どころは `gdevdocs config`（通信しない。キーの値は出さない）。

## 最初に見るべき判断フロー

```text
1. 文書名がすでに手元にあるか?
   documents/... 、前回の search の Parent: / URL: 、answer の references 、
   またはユーザーが渡した https:// URL
   Yes -> gdevdocs fetch <name-or-url>（最大20件。URL は推測して組み立てない）
   No  -> 2 へ

2. 知りたいのはコード、CLI フラグ、エラー文、手順の全体か?
   Yes -> gdevdocs search "<英語で具体化したクエリ>"
          抜粋（content）で足りなければ、そのファイルの Parent: を fetch する
   No  -> 3 へ

3. 概念の比較・説明か?
   Yes -> gdevdocs answer "<query>"
          429 なら再試行せず search に落とす（AnswerQuery は再試行しない）
          根拠ページが要る、または抜粋が足りなければ references の documents/... を fetch する
   No  -> 4 へ

4. 上のサブコマンドに無いツールや引数が要る
   -> gdevdocs tools のあと gdevdocs call <tool_name> --args '{...}'
```

`search` / `fetch` / `answer` は1回の呼び出しごとに専用フォルダを作り、結果をファイルに書く。
標準出力には **そのフォルダの `index.md` のパスだけ** が出る。まず `index.md` を読み、
各行末の文字数を見て読むファイルを選ぶ。文字数が大きいファイルはそのまま Read せず、
`aim --parallel` で必要箇所だけ抽出してよい（`aim-cli` スキル参照）。専用の digest スキルは無い。

## クエリのコツ・罠

- クエリには製品名・API 名・エラー文を入れる。言語の優劣はバケット作成の1組しか見ていない。日本語「Cloud Storage バケットの作成方法」の上位は `docs.cloud.google.com/storage/docs/creating-buckets`、英語「How to create a Cloud Storage bucket」の上位は XML API の put-bucket-create と Cluster Toolkit で、そのガイドは上位5件に無かった。結果の `URL:` を見て、外れていれば引き直す
- 検索に `data_source` フィルタは無い。結果の `URL:` を見て、聞かれた製品のページだけ残す
- `developers.google.com` には Workspace API 以外（Ads、YouTube、Maps など）も混ざる
- `knowledge.workspace.google.com` は Workspace のエンドユーザー向けヘルプである。API の根拠にしない。開発者向けは `developers.google.com/workspace`
- GCP のクライアントライブラリ参照（`docs.cloud.google.com/{cpp,dotnet,go,java,nodejs,php,python,ruby,rust}/docs/reference`）はコーパスに無い。版付き API は `use-context`
- 存在しない `documents/...` はリダイレクトせず exit 3（`Requested document was not found.`）。名前は search の `Parent:`、answer の `references`、またはユーザーが渡した URL から作る

## サブコマンド

| コマンド                                   | MCP ツール         | 用途                                                                                    |
| ------------------------------------------ | ------------------ | --------------------------------------------------------------------------------------- |
| `gdevdocs search "<query>"`                | `search_documents` | チャンク検索。入力は `query` のみ（`page_size` も `filter` も無い）。1チャンク1ファイル |
| `gdevdocs fetch <name-or-url>...`          | `get_documents`    | 最大20件。`documents/{scheme無しURI}` または `https://` URL。1文書1ファイル             |
| `gdevdocs answer "<query>"`                | `answer_query`     | 概念の回答。`answerText` と `references` を1ファイル。429 は再試行しない                |
| `gdevdocs tools`                           | `tools/list`       | サーバーが今出しているツール一覧。標準出力                                              |
| `gdevdocs call <tool_name> --args '{...}'` | 任意               | 生 JSON を標準出力。`--args` の JSON が壊れているときは exit 1                          |
| `gdevdocs config`                          | なし               | 設定の出どころ。通信しない。API キーの値は出さない                                      |

共通オプション（`config` 以外、サブコマンドの後）:

- `--endpoint <url>`: MCP エンドポイントを上書き（環境変数より上。既定は `GDEVDOCS_MCP_ENDPOINT`、無ければ `https://developerknowledge.googleapis.com/mcp`）
- `--timeout <seconds>`: リクエストタイムアウト（既定 60 秒）

## 出力形式

- `search` / `fetch` / `answer` は `GDEVDOCS_MCP_OUTPUT_DIR`（未設定時 `temp/gdevdocs_mcp`。環境変数・グローバル設定・既定値の相対パスは git ルート基準）配下に `NNNN-<スラッグ>/` を作る。再実行でも上書きせず連番が進む。並列でも連番は衝突しない
- 結果ファイルは `0001.md`, `0002.md`, ... 。`index.md` の各行末に文字数がある
- `search` の各ファイルは `#` 見出しの直後に `URL:`（`documents/` を外して `https://` を付けたもの）、`Parent:`（`documents/...`）、`Id:` を持つ。本文はチャンク
- `fetch` の `URL:` は応答の `uri`。続けて `description`、`Parent:`（`name`）、Markdown 本文
- `answer` はクエリを見出しにし、本文のあと `## References` に `documents/...` を列挙する
- `tools` / `call` / `config` はファイルを書かない

## 終了コード

| code | 意味                                                                                                                                                |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0`  | 成功                                                                                                                                                |
| `1`  | 実行時エラー（キー欠落、接続失敗、空レスポンス、429）。`search` / `fetch` の 429 は 3 秒待って1回だけ再試行したあと。`answer` の 429 は再試行しない |
| `2`  | 引数エラー（argparse、`fetch` が20件超、`documents/...` でも `https://` URL でもない引数）                                                          |
| `3`  | ツールの `is_error`。存在しない文書名は `Requested document was not found.`                                                                         |
| `4`  | 結果 0 件（stderr は `No results.`）                                                                                                                |

エラーメッセージは stderr に出る。成功時に標準出力へ出るのは `index.md` のパスだけ（`tools` / `call` / `config` を除く）。

## 他スキルとの使い分け

- **このスキル**: GCP（`cloud.google.com` の開発者ドキュメント）と Workspace の開発者向け API ドキュメント。資源の操作はしない
- **`ms-learn`**: Microsoft / Azure / .NET / M365 の公式ドキュメント
- **`aws-docs`**: AWS の公式ドキュメント
- **`use-context`**: クライアントライブラリの版付き API。GCP のクライアント参照はコーパス外なのでこちら
- **`tav-cli` / `tav-lit`**: 一般 Web、エンドユーザー向けヘルプ、このコーパスに無い URL
