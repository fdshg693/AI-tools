---
name: aws-docs
description: Search and fetch official AWS documentation (docs.aws.amazon.com, AWS Blog, What's New, re:Post Knowledge Center, CDK/CloudFormation references) and check regional availability via the self-built `awsdocs` CLI, a fastmcp wrapper around the official AWS Knowledge MCP Server (https://knowledge-mcp.global.api.aws). Use when you need AWS service docs, API/SDK/CLI references, troubleshooting articles, recent AWS launches, or whether a service/API/CFN resource is available in a region. Do not use for general web research (use `tav-cli`), Microsoft/Azure docs (use `ms-learn`), or running AWS APIs.

# 前提条件: `awsdocs`コマンドがPATH上にインストール済み
# (`uv tool install --editable tools/awsdocs`)であること。このスキルはインストール・
# セットアップは一切行わない。認証不要(AWS Knowledge MCP は公開エンドポイント、
# AWSアカウント不要)。このスキルの設計意図・前提条件の背景は同階層のREADME.md参照
# (人間のメンテナ向け)
meta:
  tag: []
  requires_repo_tools: awsdocs
  requires_env: AWSDOCS_MCP_OUTPUT_DIR, AWSDOCS_MCP_ENDPOINT
  dependencies: none
  requires_install: uv tool install --editable tools/awsdocs
  requires_hooks: none
  requires_skills: none
  status: experimental
  description: no description
  version: 0.1.1
---

## エントリポイント: `awsdocs` コマンド

```!
awsdocs --help
```

未インストール・エラーが出た場合はこのスキルでは対処しない。ユーザーに
`tools/awsdocs/README.md` のセットアップ手順を案内する。

## 最初に見るべき判断フロー

```markdown
1. 知りたいのは「あるサービス/API/CFN リソースがどのリージョンで使えるか」か?
   Yes -> awsdocs availability --type product|api|cfn --region <R> [--filter <完全一致名>]
   (フィルタ名が分からなければ単一リージョン・フィルタ無しで一覧を取り、名前を確認する)
   No -> 2 へ

2. 対象ページの URL がすでに手元にあるか(前回の search 結果、ユーザー提示など)?
   Yes -> awsdocs fetch <url>(長いページは --all)
   No -> 3 へ(URL は推測しない。理由は「罠」参照)

3. 何を探すかでトピックを1つ選んで search する:
   API/SDK/CLI の仕様 -> --topic reference_documentation
   エラー解決 -> --topic troubleshooting(エラー文をそのまま引用)
   新機能・リリース情報 -> --topic current_awareness
   CDK / CloudFormation -> --topic cdk_docs / cdk_constructs / cloudformation
   Amplify / Strands Agents -> --topic amplify_docs / strands_docs
   概念・ベストプラクティス -> トピック無し(general。Blog も混ざる)

4. search の結果ファイル(各件は約2000字の逐語チャンク)で答えられるか?
   Yes -> fetch しない(サーバーのツール説明自体がそう指示している)
   No(一覧・全件・手順全体が要る) -> 該当ファイルの `URL:` 行を awsdocs fetch に渡す

5. search 結果の skills/ に使えそうな AWS Agent Skill があれば awsdocs skill <skill_name>

6. 上記サブコマンドに無いツールや引数を使いたい(サーバー側の追加・改名)
   -> awsdocs tools で現在のツールを確認し、awsdocs call <tool_name> --args '{...}'
```

`search` / `fetch` / `skill` は1回の呼び出しごとに専用フォルダを作り、結果を1件ずつ
別ファイルに書き出す。ターミナルには **そのフォルダの `index.md` へのパスだけ** が
返る。まず `index.md` を Read してタイトル一覧(各行末に文字数付き)を見て、読む
ファイルを選ぶ。文字数が大きいファイル(`fetch --all` の全文など)はそのまま Read せず、
`aim --parallel` で必要箇所だけ抽出させてよい(`aim-cli` スキル参照)。

## クエリのコツ・罠

- **トピック未指定(`general`)だと Blog が上位に来やすい。** 例: `"S3 lifecycle rule
transition to Glacier"` を既定で引くと1位が Blog で、公式 User Guide が上位に出ない。
  公式リファレンスが欲しいときはトピックを1つ指定する(複数指定すると順位が薄まると
  サーバー説明にある。最大3)
- エラー解決はエラーメッセージをそのまま引用して `--topic troubleshooting` で引くと
  re:Post Knowledge Center の記事が当たる
- **無意味・的外れなクエリでもゼロ件にならず、無関係な結果が返る。** 結果のタイトルで
  関連性を必ず確認し、外れていればクエリを具体化して引き直す(終了コード 4 は期待しない)
- **存在しない docs URL を `fetch` すると、エラーにならずガイドのトップページに
  リダイレクトされた本文が返る**(CLI が stderr・`index.md`・ファイル先頭で警告する)。
  URL は推測で組み立てず、search 結果の `URL:` 行を使う
- 取得できる URL は AWS 系のみ(docs.aws.amazon.com、aws.amazon.com、repost.aws の
  Knowledge Center、docs.amplify.aws、strandsagents.com、一部 GitHub README 等)。
  それ以外は exit 3。一般サイトは `tav-lit` を使う
- `availability --filter` の名前は完全一致(`"AWS Lambda"`、`"Lambda+Invoke"`、
  `"AWS::Lambda::Function"`)。誤ると exit 3 で「did you mean」が stderr に出る

## サブコマンド

| コマンド                                                                                       | 用途                                                                                                         |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `awsdocs search "<query>" [--topic T]... [--limit N]`                                          | docs / Blog / What's New / re:Post / Agent Skill の横断検索。1件1ファイル。`--limit` 既定10、`--topic` 最大3 |
| `awsdocs fetch <url>... [--start-index N] [--max-length N] [--all]`                            | ページを Markdown で取得。1回既定10000字。`--all` は切り詰め分を追い読みして1ファイルに連結。複数 URL 可     |
| `awsdocs regions`                                                                              | リージョン一覧(ID と名前)を標準出力に表で出す                                                                |
| `awsdocs availability --type product\|api\|cfn --region R... [--filter F]... [--next-token T]` | 製品/API/CFN リソースのリージョン別可用性を標準出力に表で出す。複数リージョンは `--filter` 必須(最大10)      |
| `awsdocs skill <skill_name> [--file F]`                                                        | search で見つかった AWS Agent Skill の本文(既定 SKILL.md)を1ファイルに書き出す                               |
| `awsdocs tools`                                                                                | サーバーが現在提供しているツール一覧を動的に取得                                                             |
| `awsdocs call <tool_name> --args '{...}' [--no-prefix]`                                        | 任意ツールを直接呼ぶ(`aws___` プレフィックスは省略可)。生 JSON を標準出力へ                                  |

`--topic` の値: `reference_documentation`, `current_awareness`, `troubleshooting`,
`amplify_docs`, `cdk_docs`, `cdk_constructs`, `cloudformation`, `strands_docs`,
`agent_skills`, `general`(それ以外は argparse が exit 2 で弾く)。

共通オプション(サブコマンドの後に付ける):

- `--json`: ファイルを書かず、全結果を含む単一 JSON を標準出力に出す(`jq` 等へのパイプ用)
- `--endpoint <url>`: MCP エンドポイントを上書き(既定は環境変数 `AWSDOCS_MCP_ENDPOINT`、
  なければ `https://knowledge-mcp.global.api.aws`)
- `--timeout <seconds>`: リクエストタイムアウト(既定60秒)

## 出力形式

- `search` / `fetch` / `skill` は、`AWSDOCS_MCP_OUTPUT_DIR`(未設定時 `temp/awsdocs_mcp`、
  カレントディレクトリからの相対)配下に `NNNN-<クエリ or URL のスラッグ>/` の連番フォルダを
  作る。同じクエリの再実行でも上書きせず連番が進む。並列起動しても連番は衝突しない
- 結果ファイルは `0001.md`, `0002.md`, ... 。番号は全区分を通した**元の検索順位**
- `search` の結果は URL で区分され、公式 docs 以外はサブフォルダに分かれる:

  | 区分                                   | 置き場所     | `index.md` の見出し |
  | -------------------------------------- | ------------ | ------------------- |
  | docs.aws.amazon.com ほかドキュメント系 | フォルダ直下 | `## Docs`           |
  | `aws.amazon.com/blogs/`                | `blog/`      | `## Blog`           |
  | `aws.amazon.com/about-aws/whats-new/`  | `whats-new/` | `## What's New`     |
  | `repost.aws/`                          | `repost/`    | `## re:Post`        |
  | AWS Agent Skill(URL なし)              | `skills/`    | `## Skills`         |

- 各ファイルは先頭の `# ` 見出しの直後に `URL: <出典>` 行を持つ(skill エントリは
  `Skill: <skill_name>` 行。本文は `awsdocs skill <name>` で取る)
- `fetch` で切り詰められたページは、ファイル先頭と `index.md` の Warnings に「何字目で
  切れたか・続きの `--start-index`」が書かれ、本文の前にサーバーが付けた**見出しごとの
  文字範囲付き TOC** が残る。特定の節だけ欲しければその範囲を `--start-index` /
  `--max-length` で指定し、全文が要るなら `--all`
- リダイレクト(存在しない URL)は `index.md` とファイル先頭に警告、バッチ内の個別失敗は
  `index.md` の Errors に記録される
- `regions` / `availability` はファイルを書かず、標準出力に Markdown 表を出す
- `--json` 時は全結果の本文を含む単一 JSON を標準出力に出し、ファイルは一切書かない

## 終了コード

| code | 意味                                                                                                                    |
| ---- | ----------------------------------------------------------------------------------------------------------------------- |
| `0`  | 成功(存在しない URL のリダイレクトも 0。stderr の警告を確認する)                                                        |
| `1`  | 実行時エラー(接続失敗・タイムアウト・空レスポンス・レート制限。レート制限は3秒待って1回だけ自動再試行済み)              |
| `2`  | 引数エラー(argparse。不正な `--topic`、`availability` の `--region` 欠落など)                                           |
| `3`  | ツールエラー(対象外 URL・フィルタ名誤り・不明 skill 等。`fetch` のバッチで一部だけ失敗した場合も、成功分を書き出して 3) |
| `4`  | 空結果(`regions` / `availability` / `skill` が本当に空のときだけ。`search` では実質出ない)                              |

空レスポンス(exit 1)は長いページの特定範囲で断続的に起きる。`--start-index` /
`--max-length` を変えて取り直す。エラーメッセージは常に stderr に出る。

## 他スキルとの使い分け

- **このスキル**: AWS の公式ドキュメント・Blog・What's New・re:Post Knowledge Center・
  CDK/CFN リファレンス・リージョン可用性(公式一次情報・無料・認証不要)
- **`ms-learn`**: Microsoft/Azure/.NET/M365 の公式ドキュメント
- **`use-context`(`ctx7`)**: SDK・ライブラリの版依存の API(boto3、AWS SDK for
  JavaScript v3、CDK のライブラリ API 等)。まずこのスキルで `--topic reference_documentation`
  を引き、プロジェクトの固定バージョンに合わせた API シグネチャ・コード例が要るときに
  `use-context` を併用する
- **`tav-cli` / `tav-lit`**: AWS 以外のサイト、複数サイト横断の一般 Web 調査、
  このスキルで取得できない URL
- AWS API の実行・リソース操作・デプロイはこのスキルの対象外(ドキュメント参照専用)
