# skill-tools-cli スキルについて

`tools/skill-tools/`の`skill-tools` CLI（`ai-tools.yaml`登録済みスキルの一覧・配置・検索、`repo-hooks.yaml`のフック配置）を、
Claudeが会話の中からすぐ使えるようにするためのコンパニオンスキル。このファイルは人間のメンテナ向けで、
設計意図と前提条件を説明する。Claudeが実行時に読むのは[SKILL.md](SKILL.md)であり、こちらは参照しない。

併設の判断基準は[tool-companion-skills](../../../../../maintenance/docs/tool-companion-skills.md)に従う。

## なぜこのスキルがあるか

`--help`だけでは埋まらない、次の**判断**が絡む部分があるため。

- **sourceとindexをCWDから推測しない**という設計が、CLIを初めて使うエージェントの直感と食い違う。
  「今いるリポジトリのスキルが対象」ではなく設定ファイルで決まるため、結果が想定と違ったときに
  まず`config show`で解決結果を出す、という手順を固定した
- **設定の3層マージ**（組み込み既定 → グローバル → CWD）のどこを編集すべきかの判断。
  `--source`等のoverrideはCI・移行用であり常用しない、という方針もここにしか書いていない
- **`--overwrite`と`--dry-run`の使い分け**。既存skillディレクトリの上書きは破壊的なので、
  dry-run→ユーザー確認→overwriteの順を明示した
- **終了コードの意味論**（`2` catalog/config/index、`3` source、`4` filesystem install、`1` その他）。
  誤って空結果扱いすると後続処理が壊れる。特にindex未作成・別sourceのindex・APIキー未設定は
  いずれも非ゼロ終了で、`search`の「0件ヒット」ではない。一方、fingerprint不一致とindexの古さは
  stderrの警告どまりで検索は成功するため、警告と非ゼロ終了を混同させない書き分けが要る
- **`search`はsnapshotのみ**という制約。`build-index`を挟まないと最新のスキルが出ない
- **`build-index`の7日間の鮮度ゲート**。スキップ（`Index is up to date`）は成功であって失敗ではない、
  という点を明示しないとエージェントが無意味なリトライに入る。今すぐ反映したいときだけ`--force`。
  再生成しても`name`/`description`が変わらない行はベクトルを再利用するため、`SKILL.md`の本文だけを
  変えた場合の`embedded: 0`も正常、という誤解しやすい挙動をスキル側に書いた
- **table表示に`description`が出ない**ため、採否を判断するなら`--json`が要る
- **`list-tools`/`install-tools`は`release`で絞らない**（全エントリが対象）ことと、
  `install-tools`が**local source必須**（GitHub sourceでは実行不可）であること。
  全件インストールは`--dry-run`で確認してから、という順序も明示した
- **ローカル source の `install` が何を同梱するか**の判断。`.venv` / `__pycache__` などの
  生成物を除外し、判定は `tools/skill-tools/.gitignore`（除外、gitignore 構文）と
  `tools/skill-tools/.skill-tools` の `include:`（復帰、出荷時は `uv.lock` のみ）で決まること、
  `.env` は既定除外で opt-in であることを明示した。利用側で除外規則を推測させない

## 前提条件（重要）

- `skill-tools`コマンドがインストール済みであること（`uv tool install --editable tools/skill-tools`、
  または`just -f docs/integrations/justfile skill-tools-local` / `skill-tools-git`）。
  このスキルはインストール処理を一切行わない
- `search` / `build-index`を使う場合のみ`OPENROUTER_API_KEY`が必要。環境変数を優先し、
  ソースcheckoutから実行する場合だけ`tools/skill-tools/.env`に置く
- 未インストール・未設定でこのスキルが呼ばれた場合、Claudeはエラーに対処せず
  `tools/skill-tools/README.md`のセットアップ手順をユーザーに案内する

## 情報源と保守

- CLI仕様（サブコマンド・オプション・出力形式・終了コード・設定形式）の一次情報は
  `tools/skill-tools/README.md`と`tools/skill-tools/skill_tools/cli/`
- SKILL.mdはClaudeが実行時に外部ファイルへジャンプしなくて済むよう、要点を意図的に複製している。
  CLIのオプション名・出力形式・終了コードを変えたらSKILL.mdも合わせて更新し、
  `meta.version`をバンプする（[skill-md-commits](../../../../../maintenance/docs/skill-md-commits.md)）
- 影響範囲の列挙はリポジトリルートから
  `just --justfile maintenance/scripts/justfile skill-tool-impact skill-tools`

## 使い方フィードバック（`--fb`）

各ツールに`--fb`を持たせず、`skill-tools --fb`へ一本化した。スキル名・ツール名・workflow idを
同じ入口で受け、保存先も`fb.path` / `SKILL_TOOLS_FB_DIR`で実行ログと同様に設定できる。
同名のスキルとツール（`ona-run`、`linear-cli`等）を混ぜないよう、ツール利用中の不満はツール名宛て、
直す対象がスキル本文ならスキル名宛て、とSKILL.mdで分けている。個別スキルは`--fb`に言及しない。
FB導線はこのスキルだけが持つ。

いつ残すか・自動改稿しないこと・種別が曖昧なときの`--fb-kind`はSKILL.mdの判断。
フラグ・保存レイアウト・終了コードの正本は`tools/skill-tools/README.md`と
[tool-companion-skills](../../../../../maintenance/docs/tool-companion-skills.md)。

## 関連スキル

- `discovering-skills`（`maintenance/plugin/skills/discovering-skills/`）: このリポジトリでの作業開始時に
  `skill-search`サブエージェント経由で関連スキルを探しTODOへ組み込む上位の手順。
  検索の「回し方」はそちら、CLI単体の使い方はこちらが持つ
