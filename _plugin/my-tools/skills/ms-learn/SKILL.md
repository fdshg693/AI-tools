---
name: ms-learn
description: Search and fetch official Microsoft/Azure documentation (and code samples) via a self-built fastmcp CLI wrapper around the official Microsoft Learn MCP server (https://learn.microsoft.com/api/mcp). Use when you need Microsoft/Azure/.NET/M365 docs, API references, or official code samples — semantic search, full-page fetch, or code-sample lookup by language.

# 前提条件: `mslearn`コマンドがPATH上にインストール済み
# (`uv tool install --editable tools/mslearn`)であること。このスキルはインストール・
# セットアップは一切行わない。認証不要(Microsoft Learn MCP は公開エンドポイント)。
# このスキルの設計意図・前提条件の背景は同階層のREADME.md参照(人間のメンテナ向け)
meta:
  tag: []
  requires_repo_tools: mslearn
  requires_env: MSLEARN_MCP_OUTPUT_DIR
  dependencies: none
  requires_install: none
  requires_hooks: none
  requires_skills: none
  status: stable
  description: no description
  version: 1.2.3
---

## エントリポイント: `mslearn` コマンド

```!
mslearn --help
```

未インストール・エラーが出た場合はこのスキルでは対処しない。ユーザーに
`tools/mslearn/README.md` のセットアップ手順を案内する。

## 最初に見るべき判断フロー

```markdown
1. すでに対象ページの URL が分かっているか? または Learn 上の該当ドキュメントの
   URL が推測できるか?
   Yes -> mslearn fetch <url>（search は飛ばす）
   No -> 2 へ

2. 欲しいのはコードサンプルか、それとも一般的な説明/手順か?
   コードサンプル -> mslearn code-search "<query>" [--language <lang>]
   説明/手順/概念 -> mslearn search "<query>"

3. search の結果ファイルで十分な深さが取れたか?
   十分 -> そのまま使う
   途中で切れている/表面的 -> 該当結果ファイル内の `URL:` 行を mslearn fetch に渡す

4. 想定外のツールを叩きたい、または上記3ツール以外(サーバー側が新ツールを追加した等)を
   使いたい場合 -> まず `mslearn tools` で現在の提供ツールを確認し、`mslearn call <tool_name>
--args '{"...": "..."}'` で直接叩く(ツール名をハードコードしないための逃げ道)
```

`microsoft_docs_search` はチャンク化された要約(最大500トークン/件、最大10件)しか返さない。
抜粋そのものは浅いので、search は実質 **公式ページの URL を見つける** 用途が主になる。
ドキュメントの当たりがついている領域（既知の Learn セクション、前回の検索で得た URL、
製品ドキュメントの定番パス）では search を省略して直接 `fetch` する方が速い。
URL が未知で、手順の全体像やトラブルシューティングの詳細が必要なら search の後に
fetch で該当ページの全文を取る、というのが公式の想定パターン(`mslearn tools` の
出力にある "Follow-up Pattern" の説明どおり)。

`search` / `code-search` は1回の呼び出しごとに専用フォルダを作り、結果を1件ずつ
別ファイルに書き出す。ターミナルには **そのフォルダの `index.md` へのパスだけ** が
返る(個別ファイルのパスや本文は返らない)。まず `index.md` を Read してタイトル
一覧(各行末に個別ファイルの文字数も付記されている)を見て、**タイトルから読みたい
ファイルを選ぶ**。選んだファイルのうち文字数が大きいものは、そのまま Read せず
`aim --parallel` で抽出させる(`ms-digest` スキル参照) — 小さいものはそのまま Read してよい。
どのみち `index.md` は毎回開く前提なので、開く前に判断するための合計文字数のような
集計値は返さない。

## クエリの具体性を上げるコツ

- ❌ `"Azure Functions"` → ✅ `"Azure Functions Python v2 programming model timeout"`
  のように、製品名だけでなく機能名・バージョン・具体的な症状まで含める
- ただし **ARM/Bicep のリソース型名まで入れると逆効果**。
  ❌ `"Bicep Microsoft.Search searchServices Microsoft.CognitiveServices accounts"`
  は、API バージョン違いの自動生成 ARM スキーマ参照ページ（ほぼ同一のボイラープレート）
  で結果が埋まる。デプロイ手順やクイックスタートが欲しいなら
  ✅ `"Azure AI Search Bicep quickstart"` のようにチュートリアル語彙で引く
- 日本語クエリも通るが、製品名・API 名・エラーメッセージは英語の方が一致率が高い。
  日本語で結果が弱ければ英語で再実行する
- `code-search` は `--language` を付けると精度が上がる(対応言語: csharp javascript
  typescript python powershell azurecli al sql java kusto cpp go rust ruby php)

## サブコマンド

| コマンド                                            | 用途                                                                                                              |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `mslearn search "<query>"`                          | Microsoft/Azure 公式ドキュメントのセマンティック検索。チャンク化された抜粋(最大10件)を1件ずつファイルに書き出す。 |
| `mslearn code-search "<query>" [--language <lang>]` | 公式コードサンプル検索。結果を1件ずつファイルに書き出す。                                                         |
| `mslearn fetch <url>`                               | 指定 URL の Learn ページを Markdown 全文で取得し、1ファイルに書き出す。                                           |
| `mslearn tools`                                     | サーバーが現在提供しているツール一覧を動的に取得(ハードコードしない)。                                            |
| `mslearn call <tool_name> --args '{"...": "..."}'`  | 任意のツールを直接呼ぶ汎用パススルー(新ツール/引数変更への保険)。                                                 |

共通オプション:

- `--json`: 人間向けテキストの代わりに単一 JSON オブジェクトを標準出力に印字する。
  `jq` などの後段 CLI にパイプする用途向け。**このモードではファイルを書かない。**
- `--endpoint <url>`: MCP エンドポイントを上書き(既定 `https://learn.microsoft.com/api/mcp`)。
  実験的エンドポイント(`.../api/mcp/openai-compatible` 等)を試す場合に使う。
- `--timeout <seconds>`: リクエストタイムアウト(既定 30 秒)。
- `search` / `code-search` のみ: `--max-token-budget <N>`
  (`?maxTokenBudget=N` をエンドポイントに付与。search 系の結果サイズにのみ効く。
  `fetch` には効かない — サーバー側仕様)。

## 出力形式

- `search` / `code-search` / `fetch` はすべて同じ設計(`tav-lit` と同じ判断 —
  本文が数千〜数万文字になり得るため会話コンテキストを汚さない): `--json` を付けない
  場合、**1回の呼び出しごとに専用フォルダを作り、結果を1件ずつ別ファイルとして
  書き出し、ターミナルには `index.md` へのパスだけを印字する**(個別ファイルの
  パスや本文はターミナルに出ない)。
  - 書き出し先は `MSLEARN_MCP_OUTPUT_DIR` 環境変数(未設定時は `temp/mslearn_mcp`、
    カレントディレクトリからの相対解決)配下に
    `NNNN-<クエリ or URL のスラッグ>/` という連番フォルダ。**同じクエリ/URL を
    再実行しても連番が進むだけで上書きされない**(取得時点によって結果が変わり
    うるため、毎回別フォルダになる)。複数の `mslearn` を並列起動しても連番は
    衝突しない（出力ディレクトリ単位のファイルロックで採番する）。
  - フォルダ直下には結果ファイル(`0001.md`, `0002.md`, ... — タイトルは
    ファイル名でなく `index.md` 側に持つのでシンプルな連番のみ)と `index.md` を書く。
  - `search` / `fetch` の各結果ファイルは、先頭の `# ` 見出しの直後に `URL: <出典>`
    行を持つ（`aim --parallel` が出典を転記できるようにするため。`code-search` は
    `Link:` 行）。
  - `search` の結果のうち URL が `learn.microsoft.com/answers/...`
    (Microsoft Q&A のコミュニティ回答)のものは、公式ドキュメントの結果と
    混ざらないよう `qa/` サブフォルダに分離される(`code-search` / `fetch` には
    この分離はない)。
  - `index.md` には各結果ファイルへの相対リンクとタイトル(`search`/`fetch` は
    ページの `# ` 見出し、`code-search` は `description`)+ その1件の文字数が
    `## Docs` / `## Q&A` のセクション別に列挙される。まず `index.md` を読んで
    タイトルと各件の文字数を見ながら**読みたいファイルを選び**、選んだファイルの
    うち文字数が大きいものだけ `aim --parallel` に回す(`ms-digest` スキル参照)。全件の
    合計文字数のような集計値は、index.md を開く判断には使えないため出さない
    (再度 `mslearn` を呼び直す必要はない)。
- `--json` を付けた場合のみ、全結果の本文を含む単一 JSON を標準出力に出し、
  ファイルは一切書かない(`jq` などへのパイプ用途)。
- `mslearn fetch` に Microsoft Learn 以外の URL を渡すと、MCP レベルのエラーにはならず
  「The provided URL is not a valid Microsoft documentation webpage link.」という説明文が
  本文として返ってくる(終了コードは `0`)。エラー終了を期待しないこと。

## 終了コード

| code | 意味                                                                                     |
| ---- | ---------------------------------------------------------------------------------------- |
| `0`  | 成功                                                                                     |
| `1`  | 実行時エラー(接続失敗、タイムアウト、不明なツール名、`--args` の JSON パース失敗など)    |
| `2`  | 予約(argparse 自身の引数エラーで使用される)                                              |
| `3`  | ツール呼び出しが `is_error=True` を返した                                                |
| `4`  | 結果 0 件(`search` / `code-search` が空配列を返した。`fetch` が空文字を返した場合も含む) |

エラーメッセージは常に stderr に出る。`fetch` 成功時にターミナルへ印字されるのは
ファイルパスのみ(`--json` 時を除く)。

## `tav-cli` との使い分け

Microsoft/Azure/.NET/M365 の**公式ドキュメント・公式コードサンプル**が対象なら、まずこの
スキル(`mslearn`)を使う(公式一次情報・無料・認証不要・応答が速い)。それ以外の一般的な
Web 調査(非 Microsoft 系サイト、複数サイト横断のクロール、AI 要約付きリサーチなど)は
`tav-cli` / `tav-lit` を使う。
