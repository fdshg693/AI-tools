# my-agents スキルについて

`tools/my-agents/`の`my-agents` CLI(YAML定義のLangchainエージェントを実行・一覧・
新規作成するTyperツール)を、Claudeが会話の中からすぐ使えるようにするためのスキル。
このファイルは人間のメンテナ向けで、設計意図と前提条件を説明する。Claudeが実行時に
読むのは[SKILL.md](SKILL.md)であり、こちらは参照しない。

## なぜこのスキルがあるか

- `my-agents`は`run`/`list-agents`/`list-tools`/`new-agent`/`help`の5サブコマンドを
  持つが、「既存エージェントで足りるか、新規に作るべきか」「新規作成前にまず
  `list-tools`で使えるツールを確認する」といった**使い分けの判断フロー**は
  `tools/my-agents/README.md`には明示されておらず、それを固定化するためにスキル化した
- `mslearn_*`ツールが`tools/mslearn`のライブラリ薄ラップであり、検索クエリの
  具体化ノウハウ自体は`ms-learn`スキル側にある、という役割分担も運用上のノウハウ
  なのでスキル側に持たせている

## 前提条件(重要)

- リポジトリルートで`uv sync`済みであること(`uv run my-agents ...`で実行)。
  グローバルCLIとして使う場合は`uv tool install --editable tools/my-agents`でも良い
- `tools/my-agents/.env`(`.env.example`をコピー)に`OPENAI_API_KEY`が設定済みであること
- 上記が満たされていない環境でこのスキルが呼ばれた場合、Claudeはこのスキルでは
  エラーに対処せず、`tools/my-agents/README.md`のセットアップ手順をユーザーに案内する

## 情報源と保守

- CLI本体の設計思想・ファイル構成の一次情報は`tools/my-agents/PLAN.md`と
  `tools/my-agents/README.md`
- サブコマンド・オプション・エラー時の終了コードの一次情報は
  `tools/my-agents/my_agents/cli.py`本体だが、SKILL.mdはClaudeが実行時に外部ファイルへ
  ジャンプしなくて済むよう、意図的に自己完結する形で複製している。CLIのサブコマンド・
  オプション名・終了コードが変わった場合はSKILL.mdも合わせて更新すること
- 判断フロー(既存エージェント確認 → 足りなければlist-tools確認 → new-agent)は
  このスキル固有の運用方針であり、`tools/my-agents/README.md`には存在しない

二重化した内容のドリフトを防ぐため、CLI仕様を変更するときは次の順で確認する。

1. `tools/my-agents/README.md`および`my_agents/cli.py`を正本として、CLI本体と仕様を更新する
2. `SKILL.md`の「サブコマンド」「エージェント設定YAMLのフォーマット」「注意点」を
   同じ変更内容に更新する
3. サブコマンド名・オプション名・終了条件を両ファイルで突き合わせる

## 変更後の再生成

このスキルを追加・変更した場合、`CATALOG.md`(スキル一覧)と
`.claude-plugin/skill-catalog.json`は自動生成ファイルなので手で編集せず、
リポジトリルートから以下を実行して再生成する。

```bash
cd maintenance/scripts
uv run python -m plugin_meta.generate.generate_skills_catalog_md
uv run python -m plugin_meta.generate.generate_skill_catalog
```
