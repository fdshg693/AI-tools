---
name: ms-learn
description: Search and fetch official Microsoft/Azure documentation (and code samples) via a self-built fastmcp CLI wrapper around the official Microsoft Learn MCP server (https://learn.microsoft.com/api/mcp), and extract relevant parts from many result files in parallel via `aim --parallel`. Use when you need Microsoft/Azure/.NET/M365 docs, API references, or official code samples — semantic search, full-page fetch, or code-sample lookup by language.

# 前提条件: `mslearn`コマンドがPATH上にインストール済み
# (`uv tool install --editable tools/web-research/mslearn`)であること。このスキルはインストール・
# セットアップは一切行わない。認証不要(Microsoft Learn MCP は公開エンドポイント)。
# digest.md(結果ファイルの並列AI抽出)だけは `aim` コマンドと OPENROUTER_API_KEY も要る(aim-cli スキル参照)
# SKILL.md は薄いエントリ。目的別の本文は同階層の queries.md / output.md / digest.md に置く
# このスキルの設計意図・前提条件の背景は同階層のREADME.md参照(人間のメンテナ向け)
meta:
  tag: []
  requires_repo_tools: mslearn, aim
  requires_env: MSLEARN_MCP_OUTPUT_DIR, OPENROUTER_API_KEY
  dependencies: none
  requires_install: none
  requires_hooks: none
  requires_skills: aim-cli
  status: stable
  description: no description
  version: 1.3.0
---

## エントリポイント: `mslearn` コマンド

```!
mslearn --help
```

未インストール・エラーが出た場合はこのスキルでは対処しない。ユーザーに
`tools/web-research/mslearn/README.md` のセットアップ手順を案内する。

## 最初に見るべき判断フロー

```markdown
1. すでに対象ページの URL が分かっているか? または Learn 上の該当ドキュメントの
   URL が推測できるか?
   Yes -> mslearn fetch <url>（search は飛ばす）
   No -> 2 へ

2. 欲しいのはコードサンプルか、それとも一般的な説明/手順か?
   コードサンプル -> mslearn code-search "<query>" [--language <lang>]
   説明/手順/概念 -> mslearn search "<query>"

3. 返ってきた index.md を Read し、タイトルと各件の文字数から読むファイルを選ぶ
   少数・小さい -> そのまま Read
   件数が多い(目安5件以上)/大きいファイルが複数 -> digest.md の手順で並列抽出

4. search の抜粋で十分な深さが取れたか?
   十分 -> そのまま使う
   途中で切れている/表面的 -> 該当結果ファイル内の `URL:` 行を mslearn fetch に渡す

5. 上記以外のツール(サーバー側が新ツールを追加した等)を使いたい
   -> `mslearn tools` で提供ツールを確認し、`mslearn call <tool_name> --args '{"...": "..."}'` で直接叩く
```

`search` の抜粋は浅い(最大500トークン/件、最大10件)ので、search は実質 **公式ページの URL を見つける** 用途が主になる。当たりがついている領域では search を省いて直接 `fetch` する方が速い。

## 目的別ファイル

必要になった時点で、該当するファイルだけを Read する。

| やりたいこと                                                                                        | 読むファイル             |
| --------------------------------------------------------------------------------------------------- | ------------------------ |
| 検索結果が弱い・ノイズが多いので、クエリを組み直したい                                              | [queries.md](queries.md) |
| サブコマンドと共通オプション、結果フォルダ・`index.md`・`--json` の形式、終了コードを確かめたい     | [output.md](output.md)   |
| 結果ファイルが多い(目安5件以上)/大きいものが複数あり、`aim --parallel` で関連箇所だけ並列抽出したい | [digest.md](digest.md)   |

## `tav-cli` との使い分け

Microsoft/Azure/.NET/M365 の**公式ドキュメント・公式コードサンプル**が対象なら、まずこのスキル(`mslearn`)を使う(公式一次情報・無料・認証不要・応答が速い)。それ以外の一般的な Web 調査(非 Microsoft 系サイト、複数サイト横断のクロール、AI 要約付きリサーチなど)は `tav-cli` / `tav-lit` を使う。
