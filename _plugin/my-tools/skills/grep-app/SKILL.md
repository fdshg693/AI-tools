---
name: grep-app
description: Search real-world code examples across 1M+ public GitHub repositories via a self-built fastmcp CLI wrapper around the grep.app MCP server (https://mcp.grep.app). Use when you need to see how other real projects actually use an API, pattern, or library — literal code search across public GitHub, not semantic/keyword search.

# 前提条件: `grepapp`コマンドがPATH上にインストール済み
# (`uv tool install --editable tools/grepapp`)であること。このスキルはインストール・
# セットアップは一切行わない。認証不要(grep.app MCP は公開エンドポイント)。
# このスキルの設計意図・前提条件の背景は同階層のREADME.md参照(人間のメンテナ向け)
meta:
  tag: []
  requires_repo_tools: grepapp
  requires_env: GREPAPP_MCP_OUTPUT_DIR
  dependencies: none
  requires_install: none
  requires_hooks: none
  requires_skills: none
  status: stable
  description: no description
  version: 1.0.4
---

## エントリポイント: `grepapp` コマンド

```!
grepapp --help
```

未インストール・エラーが出た場合はこのスキルでは対処しない。ユーザーに
`tools/grepapp/README.md` のセットアップ手順を案内する。

## クエリの書き方(最重要の制約)

`query` は**キーワードや自然文ではなく、実際にコードに現れるリテラルなパターン**を渡す。
`searchGitHub` ツール自体の description がこの点を強調しており、キーワード検索と誤用すると
ヒット数が大きく落ちる。

- ❌ `"how to use useState hook"` → ✅ `"useState("`
- ❌ `"React import"` → ✅ `"import React from"`
- 複数行にまたがるパターンを正規表現で探したい場合は `--use-regexp` を付け、パターンの先頭に
  `(?s)` を付ける(例: `"(?s)class .+ extends React.Component"`)

## 最初に見るべき判断フロー

提供ツールが `searchGitHub` の1つだけなので、mslearn のような「URL既知/未知」「検索/取得」
分岐はない。

```markdown
1. 探しているのは「本物のプロジェクトが実際にどう書いているか」の実例か?
   Yes -> grepapp search "<リテラルなコードパターン>" [--language <lang>] [--repo <owner/repo>] [--path <path>]
   No(配布物の中身・実装・公開モジュール) -> inspecting-python-libraries
   No(概念・手順の説明が欲しい) -> このスキルの対象外。ドキュメント検索が必要なら
   ms-learn 等、対象製品に合ったスキルを使う

2. 結果が0件、または想定と違う言語/リポジトリばかり返る場合
   -> --language / --repo / --path で絞り込みを追加するか、query 自体を
   より具体的なリテラル文字列に変える(キーワードのままになっていないか疑う)

3. 想定外のツールを叩きたい、またはサーバー側が新ツールを追加した場合
   -> まず `grepapp tools` で現在の提供ツールを確認し、`grepapp call <tool_name>
--args '{"...": "..."}'` で直接叩く(ツール名をハードコードしないための逃げ道)
```

`search` の結果は最大10件固定で、ページング手段がスキーマに存在しない。1クエリで全件網羅は
期待できない前提で、絞り込みオプション(`--repo`/`--path`/`--language`)を積極的に使う。

`search` は1回の呼び出しごとに専用フォルダを作り、結果を1件ずつ別ファイルに書き出す。
ターミナルには **そのフォルダの `index.md` へのパスだけ** が返る(個別ファイルのパスや
本文は返らない)。まず `index.md` を Read してタイトル一覧(各行末に個別ファイルの文字数も
付記されている)を見て、**タイトルから読みたいファイルを選ぶ**。選んだファイルのうち
文字数が大きいものは、そのまま Read せず `aim --parallel` で抽出させる(`ms-digest` スキルと同じ
考え方) — 小さいものはそのまま Read してよい。

## 既知のリスク

- 初回呼び出しで 504 Gateway Timeout が出ることがある(コールドスタートか一時的な負荷かは
  不明)。既定タイムアウトは45秒だが、それでもタイムアウトした場合は `--timeout` を
  伸ばして(例: 60〜90秒)再実行する。
- レート制限は公式に非公開。連続で叩きすぎると 429 が返る可能性があるが、CLI側は
  リトライ・バックオフを行わない。

## サブコマンド

| コマンド                                                                                                                              | 用途                                                                                      |
| ------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `grepapp search "<query>" [--language <lang>]... [--repo <repo>] [--path <path>] [--match-case] [--match-whole-words] [--use-regexp]` | 公開GitHubリポジトリ横断のリテラルコード検索。結果(最大10件)を1件ずつファイルに書き出す。 |
| `grepapp tools`                                                                                                                       | サーバーが現在提供しているツール一覧を動的に取得(ハードコードしない)。                    |
| `grepapp call <tool_name> --args '{"...": "..."}'`                                                                                    | 任意のツールを直接呼ぶ汎用パススルー(新ツール/引数変更への保険)。                         |

`search` の絞り込みオプション:

- `--language <lang>`: 言語で絞り込み。複数回指定可(`--language TypeScript --language TSX`)。
- `--repo <owner/repo>`: リポジトリ名で絞り込み。部分一致可(`vercel/` で org 全体)。
- `--path <path>`: ファイルパスで絞り込み。部分一致可(`/route.ts` 等)。
- `--match-case`: 大文字小文字を区別する。
- `--match-whole-words`: 単語単位でマッチする。
- `--use-regexp`: `query` を正規表現として解釈する。

共通オプション:

- `--json`: 人間向けテキストの代わりに単一 JSON オブジェクトを標準出力に印字する。
  `jq` などの後段 CLI にパイプする用途向け。**このモードではファイルを書かない。**
- `--endpoint <url>`: MCP エンドポイントを上書き(既定 `https://mcp.grep.app`)。
- `--timeout <seconds>`: リクエストタイムアウト(既定 45 秒)。

## 出力形式

- `search` は `--json` を付けない場合、**1回の呼び出しごとに専用フォルダを作り、結果を
  1件ずつ別ファイルとして書き出し、ターミナルには `index.md` へのパスだけを印字する**
  (個別ファイルのパスや本文はターミナルに出ない)。
  - 書き出し先は `GREPAPP_MCP_OUTPUT_DIR` 環境変数(未設定時は `temp/grepapp_mcp`、
    カレントディレクトリからの相対解決)配下に `NNNN-<クエリのスラッグ>/` という連番
    フォルダ。**同じクエリを再実行しても連番が進むだけで上書きされない**(取得時点に
    よって結果が変わりうるため、毎回別フォルダになる)。
  - フォルダ直下には結果ファイル(`0001.md`, `0002.md`, ... — タイトルはファイル名でなく
    `index.md` 側に持つのでシンプルな連番のみ)と `index.md` を書く。各ファイルのタイトルは
    `<owner/repo> — <path>`。
  - `index.md` には各結果ファイルへの相対リンクとタイトル + その1件の文字数が列挙される。
    まず `index.md` を読んでタイトルと各件の文字数を見ながら**読みたいファイルを選ぶ**。
- `--json` を付けた場合のみ、全結果(TextContent の生テキスト配列)を含む単一 JSON を
  標準出力に出し、ファイルは一切書かない(`jq` などへのパイプ用途)。
- 結果0件の場合は stderr に `No results.` を出し、終了コード `4` を返す(ファイルは書かない)。

## 終了コード

| code | 意味                                                                                  |
| ---- | ------------------------------------------------------------------------------------- |
| `0`  | 成功                                                                                  |
| `1`  | 実行時エラー(接続失敗、タイムアウト、不明なツール名、`--args` の JSON パース失敗など) |
| `2`  | 予約(argparse 自身の引数エラーで使用される)                                           |
| `3`  | ツール呼び出しが `is_error=True` を返した                                             |
| `4`  | 結果 0 件(`search` が空応答を返した)                                                  |

エラーメッセージは常に stderr に出る。`search` 成功時にターミナルへ印字されるのは
`index.md` のパスのみ(`--json` 時を除く)。

## `ms-learn` / `tav-cli` との使い分け

- Microsoft/Azure/.NET/M365 の公式ドキュメント・公式コードサンプルが欲しいなら `ms-learn`。
- 一般的なWeb調査(非Microsoft系サイト、複数サイト横断のクロール、AI要約付きリサーチなど)は
  `tav-cli`/`tav-lit`。
- ライブラリの配布物・実装・公開モジュールを一次ソースとして読むなら
  `inspecting-python-libraries`。
- 「実際のプロジェクトのソースコードで、あるAPI/パターンがどう使われているか」を公開
  GitHub横断で見たい場合はこの `grep-app` を使う。ドキュメントの例ではなく実コードが欲しい
  ときに使う。
