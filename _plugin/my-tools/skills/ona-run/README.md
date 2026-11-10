# ona-run スキルについて

`tools/ona-run/`の`ona-run` CLI（リポジトリ+タスク指定でOnaにAIエージェント作業を委任するツール）を、Claudeが会話の中からすぐ判断・実行できるようにするためのスキル。このファイルは人間のメンテナ向けで、設計意図と前提条件を説明する。Claudeが実行時に読むのは[SKILL.md](SKILL.md)であり、こちらは参照しない。

## なぜこのスキルがあるか

[tool-companion-skills](../../../../../maintenance/docs/tool-companion-skills.md)の併設判断基準（enum/フラグの選び方、終了コードの意味論）に該当するため併設した。

- `--agent`（テンプレート）と`--command`（完全指定）のどちらを選ぶかは、対象リポジトリのDev Containerに何が導入済みかという文脈判断が必要で、`--help`だけでは分からない
- `--cleanup`の`stop`/`delete`/`keep`は用途によって選ぶべき値が異なり、決め打ちすると環境を放置して課金が続く、または調査したい環境を消してしまう
- 終了コードだけでは「タスク失敗」と「Ona側インフラ失敗」を区別できない設計（`tools/ona-run/README.md`参照）になっており、呼び出し元はstderrの`status=`マーカーを見る必要がある。この設計上の制約はCLIの`--help`には出てこない

## 前提条件（重要）

- `ona-run`コマンドは事前にインストール済みであること（`uv tool install --editable tools/ona-run`）。このスキルはインストール処理を一切行わず、CLI本体も同梱しない
- Ona公式CLI（`ona`）もインストール・`ona login`で認証済みであること。`ona-run`自体は環境変数を持たず、認証は`ona`CLI側に委譲している
- 上記が満たされていない環境でこのスキルが呼ばれた場合、Claudeはこのスキルではエラーに対処せず、`tools/ona-run/README.md`のセットアップ手順をユーザーに案内する

## 関連スキル

`--agent`/`--command`のテンプレートでは表現できない、Ona公式CLI（`ona`コマンド）自体の細かい使い方（フラグ、認証、コマンド一覧等）は[ona-cli-docs](../../../../../skills/plugins/topics/skills/ona-cli-docs/SKILL.md)スキルが担当する。こちらは`ona-run`（およびそれがラップする`ona`コマンド呼び出し）自体の設計意図・保守情報に特化する。

## 情報源と保守

- CLIオプション・終了コード・ログ形式の一次情報は`tools/ona-run/README.md`
- SKILL.mdはClaudeが実行時に外部ファイルへジャンプしなくて済むよう、上記の内容を意図的に自己完結する形で複製している。`tools/ona-run/README.md`側（オプション名・`--agent`テンプレートの中身など）が変わった場合はSKILL.mdも合わせて更新すること
- `--agent`/`--command`の選び方、`--cleanup`モードの選び方の判断基準はこのスキル固有の運用方針であり、`tools/ona-run/README.md`には（使い方としては書かれていても、判断基準としては）存在しない

二重化した内容のドリフトを防ぐため、CLI仕様を変更するときは次の順で確認する。

1. `tools/ona-run/README.md`を正本として、CLI本体と仕様を更新する
2. `SKILL.md`の「前提条件」「使い方」「終了コード・stderrマーカーの意味」「ログ」「エラー時の挙動」を同じ変更内容に更新する
3. オプション名・`--agent`テンプレートの中身・終了コード表を両ファイルで突き合わせる
