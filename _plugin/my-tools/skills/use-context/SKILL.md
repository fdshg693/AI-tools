---
name: use-context
description: Resolve and fetch current, version-aware library/framework documentation, API references, setup instructions, migration guidance, and code examples from Context7 via the self-built `ctx7` CLI (Context7's REST API directly — not the official Context7 MCP server/plugin). Activate when a task depends on an external package's current API, setup, or migration behavior. Prefer `ms-learn` for Microsoft/Azure, `aws-docs` for AWS, and `gdev-docs` for Google Cloud and Google Workspace developer documentation; do not use for general web research or local-code reading. For shipped implementation or a PyPI wheel's contents, use `inspecting-python-libraries`. Skip this skill if the official `context7-mcp` skill, the `docs-researcher` agent, or the `/context7:docs` command has already handled the same lookup in this session, to avoid duplicate calls.

# 前提条件: `ctx7`コマンドがPATH上にインストール済み
# (`uv tool install --editable tools/ctx7`)であること。このスキルはインストール・
# セットアップは一切行わない。APIキー(CONTEXT7_API_KEY)は任意(未設定でも動くが
# レート制限が低い)。このスキルの設計意図・前提条件の背景は同階層のREADME.md参照
# (人間のメンテナ向け)。
meta:
  tag: []
  requires_repo_tools: ctx7
  requires_env: CONTEXT7_API_KEY
  dependencies: requests, python-dotenv
  requires_install: uv tool install --editable tools/ctx7
  requires_hooks: none
  requires_skills: none
  status: experimental
  description: no description
  version: 1.0.5
---

## エントリポイント: `ctx7` コマンド

このスキルは常に `ctx7` CLI 経由で Context7 を呼ぶ。公式 `context7-mcp` スキルや
`docs-researcher` エージェントが同一セッションに存在し MCP ツール(`resolve-library-id`
/ `query-docs`)を提供していても、このスキルの範囲では混在させず `ctx7` に統一する
(判断基準は下記「公式スキルとの棲み分け」参照)。

```!
ctx7 --help
```

未インストール・エラーが出た場合はこのスキルでは対処しない。ユーザーに
`tools/ctx7/README.md` のセットアップ手順を案内する。

## 最初に見るべき判断フロー

```text
1. 外部ライブラリ/フレームワーク/パッケージのAPIに依存する質問か?
   No  -> Context7を呼ばず、通常の知識または別のツールを使う
   Yes -> 配布物の中身・実装・公開モジュールなら inspecting-python-libraries
          （このスキルは使わない）。ドキュメント・セットアップ・移行なら 2へ

2. Microsoft/Azure/.NET/M365、AWS、または GCP / Google Workspace の開発者向け公式ドキュメントが対象か?
   Yes -> Microsoft 系は ms-learn、AWS は aws-docs、GCP と Workspace の開発者ドキュメントは gdev-docs を優先(このスキルは使わない。
          boto3 等 AWS SDK、または GCP クライアントライブラリの版付き API が要るときだけ、公式ドキュメントの後に併用)
   No  -> 3へ

3. 公式 context7-mcp スキル・docs-researcher エージェント・/context7:docs コマンドが
   同じセッションで同じ調査対象を既に処理済みか?
   Yes -> 再度このスキルを呼ばない(二重発火を避ける)
   No  -> 4へ

4. リポジトリの manifest / lockfile / import / エラーメッセージからパッケージ名と
   バージョンを確認する(package.json, pyproject.toml, uv.lock, go.mod, Cargo.toml,
   *.csproj 等)。ユーザーの質問にバージョンが明記されていればそれを優先する。

5. ライブラリIDが既知か?
   Yes -> ctx7 docs <library-id> "<focused query>" のみ(解決ステップを省略)
   No  -> ctx7 library <name> "<task context>" で候補を取得
           -> 候補を選択(下記「候補選択の優先順位」参照)
           -> ctx7 docs <selected-id> "<focused query>"

6. query は一つの論点に絞る。複数の独立した論点がある場合は、同じ library-id を
   再利用して ctx7 docs を論点ごとに複数回呼ぶ(1回のqueryに詰め込まない)。
```

`--json`を付けなければ人間向けの整形結果(`library`は候補一覧、`docs`は生の本文
またはJSON)がそのままstdoutに出る。後段処理が要らない通常の調査では`--json`を
省いて構わない。

## 前提の抽出

ドキュメント検索の前に、可能な範囲でリポジトリの前提を先に集める。

- `package.json` / `pnpm-lock.yaml` / `package-lock.json`
- `pyproject.toml` / `uv.lock`
- `go.mod` / `Cargo.toml` / `*.csproj`
- 実際の import 文、設定ファイル、エラーメッセージ

これにより、「React の使い方」ではなく「このプロジェクトの React 19 と
React Router で、loader 後にフォーム状態を更新する方法」のような具体的なクエリを
作れる。バージョンが分からないまま最新版を前提にせず、取得結果に含まれる
バージョン情報を回答に明示する。

## `ctx7 library` — 候補選択の優先順位

`ctx7 library <name> "<task context>"` の解決用クエリには、少なくとも次を含める。

- ライブラリ名または package 名
- 実行したい操作
- フレームワークやランタイム
- バージョン、エラー、制約のうち判明しているもの

複数候補が返る場合は、名前一致 → 公式性(`trustScore`) → ベンチマークスコア・
コード例の量(`totalSnippets`)→ バージョン一致、の順に確認して一つを選ぶ。選択した
IDは、その問い合わせの間は保持し、同じ質問の途中で何度も`ctx7 library`を呼び直さない。

## `ctx7 docs` — クエリの作り方

`ctx7 docs <library-id> "<query>"` の`query`は、検索語ではなく「実装したいこと」を
自然言語で書く。

```text
悪い例: auth
悪い例: Next.js
良い例: Next.js 15 App Router で、HttpOnly cookie のセッションを middleware で
検証し、未認証ユーザーを login にリダイレクトする方法。推奨 API と注意点を知りたい。
```

良いクエリに含める要素:

- 目的: 何を実装・確認したいか
- 対象: どの API、機能、モジュールか
- 実行環境: 言語、ランタイム、フレームワーク
- バージョン: 必要なら library-id またはクエリ文に指定
- 欲しい答え: API 署名、コード例、制約、移行手順など

単一の質問で複数機能を求めない。たとえば認証・キャッシュ・ルーティングを個別に
取得し、最後に「これらを連携させる場合の制約」という統合クエリを追加する。

## 結果を評価してから実装する

返ってきた情報をそのままコードに貼り付けず、次を確認する。

1. ライブラリ名とIDが意図したものか
2. バージョンがプロジェクトと一致しているか
3. コード例の import と API が現在のコードと整合するか
4. 公式・一次ソースまたは信頼できるドキュメントか
5. 質問への直接回答になっているか
6. 非推奨 API、制約、エラー処理が欠けていないか

結果が浅い場合は、同じIDでクエリを狭めて`ctx7 docs`を再実行する。ID解決を
やり直すのは、候補選択が間違っていたと判明した場合だけにする。Context7の結果に
無いAPIを推測で補完せず、確認できなかったことを明示する。

## サブコマンド

| コマンド                                                       | 用途                                                                                   |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `ctx7 library <name> "<task context>" [--fast]`                | ライブラリ候補ID検索(`GET /api/v2/libs/search`)。`--fast`でLLM再ランキングをスキップ。 |
| `ctx7 docs <library-id> "<query>" [--type json\|txt] [--fast]` | 指定IDのドキュメントコンテキスト取得(`GET /api/v2/context`)。`--type`既定は`txt`。     |

共通オプション:

- `--json`: 自己記述エンベロープ(`{"command", "exit_code", "result"}`)をstdoutに出す。`jq`等の後段CLIへパイプする用途向け。
- `--timeout <seconds>`: リクエストタイムアウト(既定30秒)。
- `--api-key <key>`: `CONTEXT7_API_KEY`をその場だけ上書き。省略時は`.env`/環境変数を使う(未設定でも動作する)。

終了コード(`tools/mslearn`と同じ番号体系):

| code | 意味                                                                                            |
| ---- | ----------------------------------------------------------------------------------------------- |
| `0`  | 成功                                                                                            |
| `1`  | 実行時エラー(接続失敗、タイムアウト、予期しない例外)                                            |
| `3`  | Context7 APIが4xx/5xxを返した(429リトライ枯渇を含む)                                            |
| `4`  | `library`の検索結果が0件                                                                        |
| `5`  | `docs`が202(ライブラリのインデックス中)のままポーリングを使い切った。少し時間を置いて再実行する |

429・202・301の内部リトライ挙動の詳細は`tools/ctx7/README.md`の「エラー処理・
リトライ」を参照(このスキルの範囲では自動リトライ済みの結果だけを扱えばよく、
エージェント側で追加のリトライループを組む必要はない)。

## 長い調査のコンテキスト分離

短い照会は現在の会話でそのまま実行してよいが、次の場合は専用サブエージェントで
実行し、メイン会話には結論と根拠だけを返す。

- 複数ライブラリ・複数論点にまたがる調査
- 長い実装作業の途中で詳細なドキュメント検索が複数回必要
- 同じライブラリを複数の観点から比較する

分離側の返却形式は次に限定し、取得した全文をメイン会話へ戻さない。

```text
Library: <name>
Context7 ID: <id>
Version: <version or unknown>

Answer:
<必要な結論>

Implementation notes:
- <API / import / 制約>

Uncertainty:
- <確認できなかった点。なければ none>
```

ユーザー向け回答ではこの全形式を必ず表示する必要はないが、バージョンが重要な
変更ではIDとバージョンを出典として示す。

## 避けるべき利用

- 配布物の中身・実装・実際の公開モジュールを読む（`inspecting-python-libraries`）
- すべての質問で機械的にContext7を呼ぶ
- `ctx7 library`の候補を確認せず最初の結果を採用する
- ライブラリIDを知らないまま`ctx7 docs`を呼ぶ
- 「全部のドキュメント」「最新情報」だけの曖昧なクエリを投げる
- 一つのクエリに独立した論点を大量に詰め込む
- Context7の結果を、リリース直後の変更やライブ障害情報の唯一の根拠にする
- APIキーをスキル、ルール、リポジトリへ直接書き込む(`.env`または環境変数のみ)

## `ms-learn` / `aws-docs` / `gdev-docs` との使い分け

Microsoft/Azure/.NET/M365 の**公式ドキュメント・公式コードサンプル**が対象なら、
まず`ms-learn`スキルを使う(公式一次情報・無料・認証不要・応答が速い)。AWS の公式
ドキュメント(サービスガイド・CDK/CFN リファレンス・リージョン可用性)なら`aws-docs`を
使い、boto3 や AWS SDK for JavaScript v3 など SDK の版依存 API が要るときだけこのスキルを
併用する。GCP と Google Workspace の開発者向け公式ドキュメントは`gdev-docs`を使い、
クライアントライブラリの版付き API は従来どおりこのスキルを使う。それ以外の
外部ライブラリ・フレームワークの公式ドキュメント・セットアップ・移行ガイドが対象なら
このスキル(`use-context`)を使う。配布物の中身・実装・公開モジュールは
`inspecting-python-libraries`。どちらでもない一般的なWeb調査(ニュース、障害状況、製品
比較、複数サイト横断調査)は`tav-cli`を使う。Context7に未登録のライブラリや、
`ctx7`の結果だけでは裏取りが不十分な一次情報の確認にも`tav-cli`を補完的に使ってよい。

## 公式スキルとの棲み分け

Context7公式の`context7-mcp`スキル・`docs-researcher`エージェント・
`/context7:docs`コマンドは、MCPツール(`resolve-library-id`/`query-docs`)経由で
このスキルと同種の機能を提供する。ユーザー環境にこれらが導入済みの場合がある
ため、同一セッション内で同じ調査対象に対してこのスキルと公式機能を両方発火
させない。すでに公式機能側が処理していれば、このスキルは再実行しない
(上記「最初に見るべき判断フロー」の3を参照)。このスキルは`use-context`固有の
価値(`ms-learn` / `aws-docs` / `gdev-docs` とのルーティング、manifest/lockfileによるバージョン確認、ID
再利用によるクエリ分割、短い照会と長い調査のコンテキスト分離)を、公式機能が
未導入・未発火の環境で補うことを目的とする。
