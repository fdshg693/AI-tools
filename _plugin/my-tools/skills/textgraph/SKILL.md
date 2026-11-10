---
name: textgraph
description: Explains when to use the `textgraph` CLI for local file-link graphs in text files. Use when deciding among status, impact, and check, when editing Markdown or SKILL.md and needing inbound references, when choosing whether `fix --apply` is safe, when choosing `check --scripts` for script-comment links, or when falling back to grep for YAML or imports.
# 前提条件: `textgraph` コマンドが PATH 上にインストール済み（`uv tool install --editable tools/textgraph`）であること。API キーは不要。このスキルはインストール・セットアップは一切行わない。
# このスキルの設計意図・前提条件の背景は同階層の README.md 参照（人間のメンテナ向け）
meta:
  tag: []
  requires_repo_tools: textgraph
  requires_env: none
  dependencies: none
  requires_install: uv tool install --editable tools/textgraph
  requires_hooks: none
  requires_skills: none
  status: experimental
  description: テキストローカルリンクの impact / check / fix 判断
  version: 1.0.3
---

# textgraph CLI の使い方

`textgraph` はテキストファイル内のローカルファイルリンクを索引し、参照関係を返す CLI。CodeGraph がソースの呼び出し関係を見るのと同じ役割を、Markdown / SKILL.md / `.txt` などのリンクに対して持つ。MCP もファイル監視も無い。フラグの正本は `textgraph --help`。このスキルには転記しない。

## 前提条件

- `textgraph` コマンドが既にインストールされ、PATH 上で実行可能であること
- 対象は git リポジトリ。索引はリポジトリ直下の `.textgraph/`（gitignore。ソースには置かない）
- 未インストール、または索引が無い・古い場合はこのスキルでは対処しない。ユーザーに `tools/textgraph/README.md` のセットアップを案内する

## どれを使うか

索引が無いなら `init`。あるがソースより古い（未索引のテキスト追加を含む）なら `sync`。クエリ側で自動 sync はしない。件数だけ見るなら `status`（壊れ一覧は出さない）。

| 知りたいこと                                            | 使うコマンド                                                         | 使わない                       |
| ------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------ |
| ある Markdown / SKILL.md を直したとき、誰が指しているか | `textgraph impact <path>`（inbound が主、outbound は副。1 hop のみ） | 広い grep、`codegraph explore` |
| 索引上のテキストファイルの地図                          | `textgraph files`                                                    | ディスク全体の `ls`            |
| リンク切れと候補（ドキュメント）                        | `textgraph check`                                                    | いきなり `fix --apply`         |
| スクリプトコメント内の `[text](url)` / `@./` の切れ     | `textgraph check --scripts`（その場走査。索引には入れない）          | 広い grep、コードを索引する    |
| 件数・最終 sync                                         | `textgraph status`                                                   | `check` の代わり               |

`impact` の `<path>` はリポジトリ相対・絶対・basename。複数ヒットなら候補を出して止まるので、相対パスに絞る。

コードの流れ・定義・呼び出しは [codegraph-docs](../../../../../claude-plugins/topics/skills/codegraph-docs/SKILL.md)。テキストのローカル参照は textgraph。両方いるときは先にそれぞれの 1 hop を取り、混ぜて推測しない。

## `fix --apply` してよいか

先に `check`。次に `fix`（dry-run）で hunk を見る。`--apply` してよいのは一意の `unique-suffix` と `git-rename` だけ。`unique-basename` は `SKILL.md` のような短い名前を誤りやすいので、提案に留め自動適用しない。`ambiguous` も適用しない。

`--apply` 後は索引が古くなる。確認するなら `sync` してから `check`。`--scripts` で直したスクリプトは索引対象外なので、確認も `check --scripts`。lefthook にはまだ繋がない。

## grep に落とす条件

textgraph の対象外。索引は空か、誤検出になる。

- YAML / JSON のパス文字列
- コードの import / 呼び出し（codegraph）
- HTML `<a href>`、http(s) / mailto / アンカーのみ
- フェンスコードやインラインバッククォート内の見かけ上のリンク

スクリプト内の `[text](url)` と `@./` は grep に落とさない。`check --scripts` / `fix --scripts` で見る。コメント判定はしない。

未解決のまま候補が無い outbound は、移動先が git 管理下のテキストに無い可能性が高い。そのときはパス断片で grep する。
