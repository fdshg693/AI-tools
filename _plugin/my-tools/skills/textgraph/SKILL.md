---
name: textgraph
description: Explains when to use the `textgraph` CLI for local file-link graphs in text files. Use when deciding among status, impact, and check, when editing Markdown or SKILL.md and needing inbound references, when moving files and comparing link breakage before and after with `check --baseline`, when choosing whether `fix --apply` is safe, when choosing `check --scripts` for script-comment links, or when falling back to grep for YAML or imports.
# 前提条件: `textgraph` コマンドが PATH 上にインストール済み（`uv tool install --editable tools/textgraph`）であること。このリポジトリの中なら、入れずに `uv run --project tools/textgraph textgraph ...` でも動く。API キーは不要。このスキルはインストール・セットアップは一切行わない。
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
  version: 1.1.0
---

# textgraph CLI の使い方

`textgraph` はテキストファイル内のローカルファイルリンクを索引し、参照関係を返す CLI。CodeGraph がソースの呼び出し関係を見るのと同じ役割を、Markdown / SKILL.md / `.txt` などのリンクに対して持つ。MCP もファイル監視も無い。フラグの正本は `textgraph --help`。このスキルには転記しない。

## 前提条件

- `textgraph` コマンドが既にインストールされ、PATH 上で実行可能であること。このリポジトリの中で入っていなければ、`textgraph` を `uv run --project tools/textgraph textgraph` に置き換えて実行する（インストールはしない）
- 対象は git リポジトリ。索引はリポジトリ直下の `.textgraph/`（gitignore。ソースには置かない）
- 上の 2 通りとも使えない場合はこのスキルでは対処しない。ユーザーに `tools/textgraph/README.md` のセットアップを案内する
- 除外はリポジトリルートの `.textgraph.toml` だけで決まる（`status` が読んだ設定を出す）。生成物で `check` が埋まるなら、除外を足すのはユーザーに確認してから。足したら `sync`

## どれを使うか

索引が無いなら `init`。あるがソースより古い（未索引のテキスト追加を含む）なら `sync`。クエリ側で自動 sync はしない。件数だけ見るなら `status`（壊れ一覧は出さない）。

| 知りたいこと                                            | 使うコマンド                                                         | 使わない                       |
| ------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------ |
| ある Markdown / SKILL.md を直したとき、誰が指しているか | `textgraph impact <path>`（inbound が主、outbound は副。1 hop のみ） | 広い grep、`codegraph explore` |
| 索引上のテキストファイルの地図                          | `textgraph files`                                                    | ディスク全体の `ls`            |
| リンク切れと候補（ドキュメント）                        | `textgraph check`                                                    | いきなり `fix --apply`         |
| ファイル移動で増えた切れだけ                            | 移動前に `check --json` を保存し、移動後に `check --baseline`        | 移動前後の表を目で diff        |
| スクリプトコメント内の `[text](url)` / `@./` の切れ     | `textgraph check --scripts`（その場走査。索引には入れない）          | 広い grep、コードを索引する    |
| 件数・最終 sync                                         | `textgraph status`                                                   | `check` の代わり               |

`impact` の `<path>` はリポジトリ相対・絶対・basename。複数ヒットなら候補を出して止まるので、相対パスに絞る。

`check` が出すのは切れだけではない。書かれたパスのままでは当たらず suffix や basename で当たったリンク（移動で `../` の段数がずれたものなど）も `suggested` として出る。これは直す対象として扱う。

索引の外でもディスクに実在するリンク（アンブレラからサブモジュールの中、サブモジュールからアンブレラ、gitignore された生成物）は `external` で、既定では一覧にも終了コードにも入らず、stderr に件数だけ出る。切れではないので直さない。サブモジュールをまたぐリンクの切れを調べたいときだけ `--external` で一覧に出す。

### ファイルを移動するとき

移動前に `check --json > before.json`（作業用の場所に置き、コミットしない）。`git mv` して `sync` したら `check --baseline before.json`。出た行が移動で増えた切れで、移動したファイル自身の既存の切れは rename を辿って読み替えるので新規に数えない。`--scripts`・`--external` は baseline を取ったときと揃える。

作業ツリーだけの `mv` は git が rename として見ないので、`git mv` するか `git add -A` してから `check` / `fix` する（stage 済みの rename は `git-rename` 候補になる）。

コードの流れ・定義・呼び出しは [codegraph-docs](../../../../../skills/plugins/topics/skills/codegraph-docs/SKILL.md)。テキストのローカル参照は textgraph。両方いるときは先にそれぞれの 1 hop を取り、混ぜて推測しない。

## `fix --apply` してよいか

先に `check`。次に `fix`（dry-run）で hunk を見る。`--apply` してよいのは一意の `unique-suffix` と `git-rename`（旧パスが完全一致した rename）だけ。CLI もこの 2 つしか書き換えない。

- `git-rename-basename`（basename だけで当たった rename）と `unique-basename` は、`index.md`・`README.md`・`SKILL.md` のような短い名前で無関係なファイルを指しやすい。提案に留め、採るなら目で確かめて手で直す
- `ambiguous` は適用しない。候補はリンクのディレクトリ名を含むものに絞られているので、そこから選んで手で直す
- `external` は実在するリンクなので直さない

`--apply` 後は索引が古くなる。確認するなら `sync` してから `check`。`--scripts` で直したスクリプトは索引対象外なので、確認も `check --scripts`。lefthook にはまだ繋がない。

## grep に落とす条件

textgraph の対象外。索引は空か、誤検出になる。

- YAML / JSON のパス文字列
- コードの import / 呼び出し（codegraph）
- HTML `<a href>`、http(s) / mailto / アンカーのみ
- フェンスコードやインラインバッククォート内の見かけ上のリンク

スクリプト内の `[text](url)` と `@./` は grep に落とさない。`check --scripts` / `fix --scripts` で見る。コメント判定はしない。

未解決のまま候補が無い outbound は、移動先が git 管理下のテキストに無い可能性が高い。そのときはパス断片で grep する。
