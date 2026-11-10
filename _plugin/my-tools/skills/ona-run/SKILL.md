---
name: ona-run
description: リポジトリURL（またはOnaプロジェクトID）とタスク内容を指定してOnaの環境（コンテナ）を作成・起動し、その中でAIエージェントCLI等のタスクを実行して完了後に停止する`ona-run` CLIツールの使い方を説明する。`--agent`/`--command`の選び方、`--cleanup`モードの選び方、終了コード・stderrマーカーの意味を判断したい場合に使う。
# 前提条件: `ona-run`コマンドがPATH上にインストール済み（`uv tool install --editable tools/ona-run`）であり、Ona公式CLI（`ona`）もインストール・`ona login`で認証済みであること。ona-run自体は追加の環境変数を必要としない
# コンテナ内でAIエージェントCLI（claude/codex）を動かす場合、対象リポジトリのDev Container側にそのCLIが導入済みであることが前提（このスキル・ツールとも導入までは面倒を見ない）
# このスキルの設計意図・前提条件の背景は同階層のREADME.md参照（人間のメンテナ向け）
meta:
  tag: []
  requires_repo_tools: ona-run
  requires_env: none
  dependencies: none
  requires_install: uv tool install --editable tools/ona-run, ona CLI + ona login
  requires_hooks: none
  requires_skills: none
  status: stable
  description: no description
  version: 1.0.4
---

# ona-run CLI の使い方

`ona-run`は「リポジトリURL（またはOnaプロジェクトID）」と「タスク内容（自然文プロンプト）」を指定すると、Onaの環境（コンテナ）を作成/起動し、その中でタスクを実行し、完了後に環境を停止する単一コマンドのCLI。Ona公式CLI（`ona environment create`/`get`/`exec`/`stop`/`delete`）をsubprocessでラップするだけで、Connect-RPC APIの再実装はしない。

## 前提条件

- `ona-run`コマンドが既にインストールされ、PATH上で実行可能であること
- Ona公式CLI（`ona`）がインストール済み、かつ`ona login`で認証済みであること（`ona-run`自体は認証情報を持たず、`ona`CLI側の認証に依存する）
- 未インストール・未認証の場合はこのスキルでは対処しない。エラーが出た場合はユーザーに`tools/ona-run/README.md`のセットアップ手順を案内する
- コンテナ内でAIエージェントを動かす場合（`--agent claude`/`--agent codex`）、対象リポジトリのDev Container側にそのCLIが導入済みであること。導入されていない場合は`--agent`ではなく`--command`でその場に合わせたセットアップコマンドを組み立てるか、ユーザーに確認する

## `--agent` と `--command` の選び方

コンテナ内で実行するコマンドは`--agent`（簡易テンプレート）と`--command`（完全指定）のどちらか一方が必須。

| 状況                                                                                                                                                        | 選ぶオプション                                                                                          |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| 対象リポジトリのDev ContainerにClaude Code CLIまたはCodex CLIが入っているとわかっている、かつ既定のheadlessフラグで問題ない                                 | `--agent claude` または `--agent codex`                                                                 |
| Dev Containerに入っているCLIのバージョンが既定フラグと合わない、別のエージェントCLIを使いたい、複数コマンドを組み合わせたい等、テンプレートでは表現できない | `--command` で完全なargvを指定する                                                                      |
| Dev Containerに何が入っているか分からない                                                                                                                   | 事前にユーザーに確認するか、`--command`で対象CLIの存在確認コマンドを挟む。決め打ちで`--agent`を選ばない |

`--agent`が組み立てる実際のコマンド:

| `--agent` | 組み立てるコマンド                                               |
| --------- | ---------------------------------------------------------------- |
| `claude`  | `claude -p "<task>" --dangerously-skip-permissions`              |
| `codex`   | `codex exec --dangerously-bypass-approvals-and-sandbox "<task>"` |

いずれも「Onaのコンテナ自体が外部サンドボックスである」ことを前提に、確認プロンプトなしで自律実行するフラグ。`--command`を使う場合も同様の非対話フラグを付けないとタスクが確認待ちでハングする点に注意する。

`--command`使用時は`{task}`がタスク文字列に置換される。`--command`は以降の全トークンをそのままコマンドとして扱うため、他のオプションより後ろ・末尾に置く。

`ona-run`自体が内部で組み立てる`ona environment exec`コマンドの詳細（利用可能なフラグ等）を知りたい場合や、`ona-run`の抽象化では表現できず素のOna公式CLI（`ona`コマンド）を直接操作する必要がある場合は、[ona-cli-docs](../../../../../skills/plugins/topics/skills/ona-cli-docs/SKILL.md)スキルを参照する。

## `--cleanup` モードの選び方

| 状況                                                   | 選ぶ値                                                                                                        |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| 通常運用（既定）                                       | `stop`。環境の状態を残したまま停止し、再開・調査が可能                                                        |
| タスクが失敗した・結果を対話的に確認したい・デバッグ中 | `keep`。環境を起動したままにする（Ona既定のinactivity timeoutで自動停止されるまで課金対象になりうる点に注意） |
| 使い捨て検証で環境自体を残す必要がない                 | `delete`。環境ごと削除する                                                                                    |

判断に迷う場合はデフォルトの`stop`のままにする。`keep`/`delete`はユーザーが明示的に意図した場合のみ選ぶ。

## 使い方

```bash
# --agent: 簡易テンプレート
ona-run https://github.com/example/repo "READMEのtypoを直してPRを作って" --agent claude

# タスクは省略時、標準入力から読み込む
echo "READMEのtypoを直してPRを作って" | ona-run https://github.com/example/repo --agent claude

# --command: コンテナ内で実行する完全なコマンドをargvのトークン列として指定する（末尾に置く）
ona-run https://github.com/example/repo "タスク内容" --cleanup delete \
  --command claude -p "{task}" --dangerously-skip-permissions
```

| オプション        | 必須 | 説明                                                                                                            |
| ----------------- | ---- | --------------------------------------------------------------------------------------------------------------- |
| `repo_or_project` | ○    | 位置引数。リポジトリURL、またはOnaプロジェクトID                                                                |
| `task`            | △    | 位置引数。タスク内容（自然文プロンプト）。省略時は標準入力から読み込む                                          |
| `--agent`         | △    | `claude`/`codex`。`--command`と同時指定不可、どちらか一方が必須                                                 |
| `--command`       | △    | コンテナ内で実行する完全なコマンド（argvのトークン列）。`--agent`と同時指定不可、どちらか一方が必須。末尾に置く |
| `--cleanup`       | -    | `stop`/`delete`/`keep`（既定: `stop`）                                                                          |
| `--class-id`      | -    | 環境クラスID（省略時は自動解決を試みる）                                                                        |
| `--start-timeout` | -    | 環境がRUNNINGになるまでの待機タイムアウト秒（既定: 300）                                                        |
| `--task-timeout`  | -    | タスク実行のタイムアウト秒（既定: 1800）                                                                        |

## 終了コード・stderrマーカーの意味

`--command`で渡す任意のコマンドは0〜255のどの終了コードでも返しうるため、終了コード単体では「タスク失敗」と「Ona側インフラ失敗」を100%区別できない。判定にはstderrの`ona-run: status=...`マーカーを一次情報として使う。

| 状況                                   | 終了コード                   | stderrマーカー                |
| -------------------------------------- | ---------------------------- | ----------------------------- |
| 環境作成・起動待ち自体が失敗           | 固定`64`                     | `ona-run: status=infra_error` |
| タスク（`ona environment exec`）が失敗 | タスクの終了コードをそのまま | `ona-run: status=task_failed` |
| 成功                                   | `0`                          | `ona-run: status=success`     |

クリーンアップ（`stop`/`delete`）自体の失敗は警告をstderrに出すのみで、上記の戻り値は上書きしない。呼び出し元のスクリプト等で結果を分岐させる場合は、終了コードだけでなくstderrの`status=`マーカーを確認する。

## ログ

実行ごとに`tools/ona-run/logs/runs.jsonl`（JSON Lines）へ1行追記される（`timestamp`/`env_id`/`repo`/`agent`/`exit_code`/`duration_seconds`のみ）。タスク本文・stdout/stderrは含めない。`repo`にトークン付きURLを渡した場合、そのトークンが平文でログに残る点に注意する。

## エラー時の挙動

`ona`未インストール・未認証、環境作成失敗、タスクタイムアウト等が発生した場合、`ona-run`はエラーメッセージを標準エラー出力に表示し、非ゼロで終了する（詳細は上記「終了コード・stderrマーカーの意味」参照）。未インストール・未認証が原因の場合はこのスキルでは対処せず、`tools/ona-run/README.md`のセットアップ手順をユーザーに案内する。
