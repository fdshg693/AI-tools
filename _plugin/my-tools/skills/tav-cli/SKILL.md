---
name: tav-cli
description: Guides multi-step Tavily research with this project's `tav` command, including web-wide search, multiple URLs, site maps/crawls, topic-based result accumulation, and parallel AI extraction of many collected pages via `aim --parallel`. Use when a task needs more than one known URL or a reusable research workspace; use `tav-lit` to extract one already-known URL.

# 前提条件: `tav`コマンドがPATH上にインストール済み
# (`uv tool install --editable tools/web-research/tav-cli`)であること。このスキルはインストール・
# セットアップは一切行わない。CLI本体は同梱せず、Pythonスクリプトを直接叩く運用は廃止した
# (実体は tools/web-research/tav-cli/ を参照)。
# 実行前に TAVILY_API_KEY を環境変数、またはグローバル設定 ~/.config/tav/config.toml の api_key に設定していること
# 出力先などはプロジェクト設定 .tav.toml(CWD〜git ルートで近いものが勝つ)・グローバル設定・環境変数で設定でき、TAVILY_OUTPUT_DIR(出力先ベース、未設定時は git ルート基準の temp/web)・TAVILY_WRITE_LOG(監査ログ出力トグル、未設定=true)・TAVILY_SHOW_LOG_PATH(監査ログ書き込み時の「Wrote full log to <path>」通知トグル、未設定=true。結果ファイルのパス通知は常に表示)も設定できる
# digest.md(pages/ の並列AI抽出)だけは `aim` コマンドと OPENROUTER_API_KEY も要る(aim-cli スキル参照)
# SKILL.md は薄いエントリ。目的別の本文は同階層の commands.md / output.md / digest.md に置く
# このスキルの設計意図・前提条件の背景は同階層のREADME.md参照(人間のメンテナ向け)

# ```!```を使った動的コンテキスト埋め込みを使い、更新漏れを防止する
# 参考: https://code.claude.com/docs/en/skills#inject-dynamic-context
meta:
  tag: []
  requires_repo_tools: tav, aim
  requires_env: TAVILY_API_KEY, TAVILY_OUTPUT_DIR, TAVILY_LOG_DIR, TAVILY_WRITE_LOG, TAVILY_SHOW_LOG_PATH, OPENROUTER_API_KEY
  dependencies: tavily-python
  requires_install: uv tool install --editable tools/web-research/tav-cli
  requires_hooks: none
  requires_skills: aim-cli
  status: stable
  description: no description
  version: 1.3.0
---

## エントリポイント: `tav` コマンド

```!
tav --help
```

未インストール・エラーが出た場合はこのスキルでは対処しない。ユーザーに
`tools/web-research/tav-cli/README.md` のセットアップ手順を案内する。

## 最初に見るべき判断フロー

```text
1. すでに対象 URL が分かっているか?
   Yes -> tav extract
   No  -> 2 へ

2. すでに対象サイトのルート URL が分かっているか?
   Yes -> 3 へ
   No  -> 4 へ

3. サイトに対して何をしたいか?
   ページ一覧や構造を見たい              -> tav map
   サイト本文を一気に回収したい          -> tav crawl
   先に候補 URL を見てから本文抽出したい -> tav map-extract

4. 手元にあるのは topic / question / keyword だけか?
   Yes -> 5 へ
   No  -> 追加の入力条件を整理してから再判定

5. キーワード起点なら何がほしいか?
   まず関連 URL と要約だけ見たい        -> tav search
   まず根拠 URL を広く集めたい           -> tav search
   関連 URL の本文まで続けて取りたい     -> tav search-extract
   AI に調査と要約まで任せたい           -> tav research
```

迷ったら、topic 起点は `tav search`、URL 起点は `tav extract`、サイト起点は `tav map`。
URL 本文の取得は `tav extract` を使い、Python などで直接 HTML を取らない。
調査タスク単位で結果をためるときは `--topic <slug>` を付ける。

## 目的別ファイル

必要になった時点で、該当するファイルだけを Read する。

| やりたいこと                                                                                                                    | 読むファイル               |
| ------------------------------------------------------------------------------------------------------------------------------- | -------------------------- |
| コマンドごとの用途、`--detail` プリセット、クエリ言語・ドメインフィルタ、並列数・レート、シェルの注意                           | [commands.md](commands.md) |
| `--topic` の保存先と役割サブフォルダ、`pages/index.json`、出力エンベロープ、終了コード                                          | [output.md](output.md)     |
| `pages/` の件数が多い(目安5件以上)、または `char_count` の大きいページが複数あり、`aim --parallel` で関連箇所だけ並列抽出したい | [digest.md](digest.md)     |

`pages/` のページが1〜2件、または小さいページだけなら digest.md は不要。そのまま Read する。
