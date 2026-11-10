# gdev-docs スキルについて

`tools/gdevdocs/` の `gdevdocs` CLI（fastmcp で自作した、公式 Developer Knowledge MCP のラッパー）を、会話の中から使い分けるためのスキル。このファイルは人間のメンテナ向けで、設計意図と前提条件を説明する。実行時に読むのは [SKILL.md](SKILL.md) であり、こちらは参照しない。

## なぜこのスキルがあるか

- CLI には `search` / `fetch` / `answer` / `tools` / `call` / `config` があるが、「コードやエラー文は `search`」「概念比較は `answer`」「抜粋が足りなければ `Parent:` か `references` を `fetch`」という判断フローは `tools/gdevdocs/README.md` には無い
- コーパスにドメインフィルタが無いこと、Workspace ヘルプの混入、クライアントライブラリ参照の除外は、CLI の仕様ではなく結果の読み方なのでスキル側に持たせている
- 公式の Agent Skill（`google/skills` の `retrieving-developer-knowledge`）はインストールしない。結果をファイルと後段ツールに渡すのは自作 CLI 経由にする（`ms-learn` / `aws-docs` と同じ）

## 前提条件

- `gdevdocs` は事前にインストール済みであること（`uv tool install --editable tools/gdevdocs`）。このスキルはインストールを行わない
- `GDEVDOCS_API_KEY` が環境変数かグローバル設定で解決できること。プロジェクトの `.gdevdocs.toml` とリポジトリルートの `.env` は CLI が読まない
- キーを発行したプロジェクトで Developer Knowledge API（`developerknowledge.googleapis.com`）が有効であること
- 未導入のときは、このスキルではエラーに対処せず `tools/gdevdocs/README.md` のセットアップを案内する

## 情報源と保守

CLI 仕様の正本は `tools/gdevdocs/README.md` と `gdevdocs_cli.py`。SKILL.md は実行時にそこへ飛ばなくて済むよう、「サブコマンド」「出力形式」「終了コード」を複製している。

判断フロー、クエリのコツ、他スキルとの境界はスキル固有であり、CLI の README には無い。

二重化した内容をずらさないため、CLI 仕様を変えるときは次の順で確認する（`tools/gdevdocs/AGENTS.md` にも同じ規約がある）。

1. `tools/gdevdocs/README.md` と `gdevdocs_cli.py` を正本として CLI を更新する
2. `SKILL.md` の「サブコマンド」「出力形式」「終了コード」を同じ変更にする
3. オプション名・出力形式・終了条件を両ファイルで突き合わせる

## スコープ外にしたもの

- 大きい結果の専用 digest スキルは作らない。SKILL.md で `aim --parallel` を案内する
- GCP / Workspace の資源操作は扱わない
- 他の AI ツール向けへの横展開はしない（`ms-learn` と同じく `tools/_plugin/my-tools` のみ）
