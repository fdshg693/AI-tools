---
name: skill-tools-cli
description: ai-tools.yamlに登録済みのAgent Skillを一覧・他プロジェクトへ配置・本文ハイブリッド検索し、目的別workflowを確認し、repo-hooks.yamlのエージェントフックを配置・登録する`skill-tools` CLIの使い方を説明する。手元のプロジェクトへスキルやフックを導入したい、配布対象やworkflowを確認したい、自然文や本文語彙でスキルを検索したい、source（local clone / GitHub）やindexの解決結果を確認したい、スキル・ツール・workflowの使い方フィードバックを`skill-tools --fb`で残したい場合に使う。スキルの新規作成・SKILL.mdの編集自体は対象外。
# 前提条件: `skill-tools`コマンドがPATH上にインストール済み（`uv tool install --editable tools/skill-tools`）であり、
# search / build-index を使う場合は OPENROUTER_API_KEY が設定済みであること。このスキルはインストール・セットアップは一切行わない
# このスキルの設計意図・前提条件の背景は同階層のREADME.md参照（人間のメンテナ向け）
meta:
  tag: []
  requires_repo_tools: skill-tools
  requires_env: OPENROUTER_API_KEY
  dependencies: none
  requires_install: uv tool install --editable tools/skill-tools
  requires_hooks: none
  requires_skills: none
  status: experimental
  description: skill-tools CLIのsource解決・install選択子・index運用・フック配置・使い方FBの判断基準
  version: 1.2.5
---

# skill-tools の使い方

`skill-tools`は`ai-tools.yaml`に登録された plugin / workspace root 配下の`SKILL.md`バンドルを、一覧（`list-skills`）・他プロジェクトへの配置（`install-skills`）・本文語彙と意味検索を組み合わせたハイブリッド検索（`search` / `build-index`）で扱うCLI。加えて、同じsourceの`repo-tools.yaml`に登録された`tools/`配下のCLIツールを`list-tools`/`install-tools`で列挙・インストールし、`repo-workflows.yaml`の目的別workflowを表示し、`repo-hooks.yaml`が指すフックカタログのエージェントフックを`hooks`サブコマンドで配置・登録できる。スキル本文の作成・編集や、各SSOTへの登録自体は扱わない。

## 前提条件

- `skill-tools`コマンドがインストール済みでPATH上にあること
- `search` / `build-index`を使うときだけ`OPENROUTER_API_KEY`が必要（`list-skills` / `install-skills` / `config`は不要）
- 未インストール・未設定なら、このスキルでは対処せず`tools/skill-tools/README.md`のセットアップ手順をユーザーに案内する

## 最初に理解しておくこと: 対象範囲とsourceの解決

このCLIが判断を誤りやすいのは、次の2点を暗黙に推測**しない**設計だからである。

- **対象は`ai-tools.yaml`登録分だけ。** `maintenance/plugin/`配下（`meta`・`discovering-skills`等）は未登録なので`list-skills`にも`search`結果にも出ない。「あるはずのスキルが出ない」ときはまずここを疑う。仕様どおりなので修正しない。
- **sourceは実行時のCWDから推測しない。** 「今いるリポジトリのスキル」が対象になるわけではない。source（`local`のclone パス、または`github`のowner/repo/ref）とindexの位置は設定ファイルで決まる。CWDは「どのプロジェクトへ配置するか」にしか使わない。

結果が想定と違うときは、何をやり直すより先に解決結果を出す。

```powershell
skill-tools config show
```

出力は採用した設定ファイル、グローバル設定とCWD設定のパス、`source.type`、index path、`fb.path`、`self_skill`、fingerprint / 解決済み commit、この CLI 自身の場所（`package.pyproject` / `package.readme`）。APIキーの値は出ない。`source.*` はスキルカタログの取得元で、CLI 自身の位置ではない。`list-skills`・`build-index`は解決済みsourceをstderrへ`source: ...`で出すので、標準出力をパイプしてもsourceの確認はできる。

### 設定の層と、どれを触るか

1. 組み込み既定値（GitHub `fdshg693/ai@main` + OSのキャッシュ領域）
2. グローバル設定（`%APPDATA%/skill-tools/skill-tools.yaml` またはXDG設定ディレクトリ）— `skill-tools config init`で作成
3. 実行CWDの`skill-tools.yaml`（プロジェクト固有の上書き）

後の層が優先。**全プロジェクト共通の既定を変えるならグローバル設定、このプロジェクトだけの配置先を決めるならCWDの`skill-tools.yaml`**を編集する。`--config` / `SKILL_TOOLS_CONFIG`を渡した場合はこのマージを行わず、その1ファイルだけを使う（CI・移行時の挙動固定用であり、通常運用で使わない）。

`--source` / `--repo` / `--github-*` / `--index-path`も同じくCI・移行用のoverride。**通常はこれらを毎回付けず、設定ファイルにsourceを書く。** コマンド例にoverrideが並んでいるのを見て常用しないこと。

```yaml
source:
  type: local # local | github の2択のみ
  path: C:/src/ai

index:
  path: ~/.cache/skill-tools/skill-index.json

# `install-skills self` の展開先（省略時はこの既定値）
self_skill: tools/_plugin/my-tools/skills/skill-tools-cli/SKILL.md

skills:
  skills/plugins/coding/skills/testing/SKILL.md:
    destination: .agents/skills
```

複数の配置先を使う場合は、project-relative destinationをnamed targetとして定義する。

```yaml
targets:
  claude:
    destination: .claude/skills
  agents:
    destination: .agents/skills
skills:
  skills/plugins/coding/skills/testing/SKILL.md:
    destinations:
      agents: .agents/custom-skills
```

install成功時の配置はプロジェクトの`.skill-tools/manifest.json`に記録される。manifestの共有や`.gitignore`の変更は自動では行わない。local sourceがプロジェクト外にある場合、その絶対pathがmanifestに残ることがあるため、共有前に確認する。

## `list-skills` — 配布対象スキルの一覧

```powershell
skill-tools list-skills
```

`source path<TAB>skill name<TAB>file count`をタブ区切りで標準出力へ出す。source pathは local なら`SKILL.md`の絶対パス、GitHub なら`https://github.com/<owner>/<repo>/blob/<commit>/<path>`。この source path は次の`install-skills`にそのまま渡せる選択子なので、`install-skills`の前に`list-skills`で実体を確認するのが基本の流れ。

## `install-skills` — 現在のプロジェクトへスキルを配置

```powershell
skill-tools install-skills alpha
skill-tools install-skills skills/plugins/coding/skills/testing/SKILL.md --dry-run
skill-tools install-skills alpha --overwrite
skill-tools install-skills --target claude,agents alpha --dry-run
skill-tools install-skills self
```

- **`self`は予約語。** 設定の`self_skill`（既定は`tools/_plugin/my-tools/skills/skill-tools-cli/SKILL.md`、つまりこのスキル自身）のcanonical IDへ展開され、以後は通常のinstallと同じ配置・manifest・`--dry-run` / `--overwrite` / `--target`を使う。カタログ上に`self`という名前のスキルがあっても`self`が優先されるので、そのスキルを入れたいときはcanonical IDを渡す。`self other-name`は両方を入れる
- **引数なしの`install-skills`は全件インストールにならずエラー。** `install-tools`と違い、スキルの全件配置はしない
- `self_skill`の値は設定ロード時に存在確認しない。カタログに無ければinstall時に`skill not found`（終了コード`2`）になる
- 旧名（`list` / `install` / `installed` / `update` / `remove`）は廃止済みで、未知のコマンドとしてエラーになる。コマンドは`list-skills` / `install-skills` / `installed-skills` / `update-skills` / `remove-skills`を使う

- 選択子は **source path / リポジトリ相対の canonical ID（`skills/plugins/.../SKILL.md`） / 一意なskill名** のいずれか。名前が一意でないときは canonical ID か source path を使う
- 配置先はCWD基準。既定は`.claude/skills/<skill-name>/`。`.agents/skills/`等へ変えるなら`skill-tools.yaml`の`skills:`に canonical ID ごとの`destination`を書く
- `--target name[,name...]`を指定すると、同じbundleを複数targetへ配置する。`targets.<name>.destination`がtargetの既定配置先で、`skills.<canonical-id>.destinations.<target>`がskill単位の上書き。target指定時の優先順位はskill target override → target既定 → legacy `skills.<id>.destination` → `.claude/skills`。`--target`未指定時はこれまでのdestination設定・既定値を維持する
- **既存のskillディレクトリは`--overwrite`なしでは変更しない。** 上書きになる場合はまず`--dry-run`で配置先を確認し、ユーザーに上書き可否を確認してから`--overwrite`を付ける
- `--dry-run`はコピーせず、target指定時には`would install<TAB>source path<TAB>canonical ID<TAB>target名<TAB>最終相対path`をtargetごとに表示する。target未指定時の既存出力は変わらない
- 全bundle×targetをstagingしてから置換し、途中で失敗したら完了済みの置換をrollbackする。project単位lockでinstallを直列化し、lock内でもdestinationを再検証する。中途半端な状態を手で片付ける前提で組まない
- **ローカルsourceのコピーでは`.venv`/`__pycache__`/`node_modules`等の生成物を同梱しない。** 判定は`tools/skill-tools/.gitignore`（除外、gitignore構文）と`tools/skill-tools/.skill-tools`の`include:`（復帰）で決まり、利用側で推測しない。`include:`は出荷時`uv.lock`のみで、`.env`は既定除外（コピーさせたい場合だけ利用者が追記する）
- 配置後に新しいskillがAIツールに出てこない場合は、セッションまたはIDEの再起動を案内する（CLI側の失敗ではない）

### `installed-skills` / `update-skills` / `remove-skills` — managed skillの確認・更新・削除

```powershell
skill-tools installed-skills
skill-tools installed-skills --json
skill-tools update-skills alpha --dry-run
skill-tools update-skills alpha
skill-tools remove-skills alpha --dry-run
skill-tools remove-skills alpha
```

- `installed-skills`はmanifestだけを読み、sourceやnetworkを参照しない
- `update-skills`はmanifestを起点に同じsource identityのentryだけを扱う。GitHubは記録されたrefを再解決し、別repo/refへの暗黙切替は拒否する。catalogから消えたskillは削除せず警告する
- `remove-skills`はmanifest entryだけを対象にし、source・catalog・networkを必要としない。未管理directoryは検索・削除しない
- `update-skills` / `remove-skills`はhash drift・欠落・追加file・symlinkがあれば既定で中止する。`--force`は対象managed directory内の変更を置換・削除し得るため、先に`--dry-run`で対象を確認する。symlinkやproject外pathの拒否はforceでも無効化しない
- install-skills/update-skills/remove-skillsはjournalで中断を記録する。process termination時は次回managed操作でrollbackを試みるが、複数pathの完全な原子性や電断・storage障害時の復旧は保証しない

## `list-tools` / `install-tools` — repo-tools.yaml のCLIツール

```powershell
skill-tools list-tools
skill-tools list-tools --json
skill-tools install-tools --dry-run
skill-tools install-tools aim tav
```

- 対象はsource（設定中の`source`）の`registry/repo-tools.yaml`（無ければルートの`repo-tools.yaml`）の全エントリ。**`release`の値では絞らない**（タグ+Release対象かどうかは別の軸であり、`release: false`や未設定のツールも含めて全件が列挙・インストール対象）
- `list-tools`は`tool name<TAB>path<TAB>install command<TAB>summary`の4列をタブ区切りで標準出力へ出す。`summary`は`repo-tools.yaml`の`description` locator（`tools/.../pyproject.toml#project.description`、READMEパス等）を解決した1行概要で、locator未指定なら空。locatorが壊れているとツール名とlocatorを出して終了コード`2`で止まる。**概要を機械的に扱うなら`--json`**（`{name, path, install, description}`の配列。stderrの`source: ...`は同じ）。最初にこれで登録名と`install`コマンドを確認する
- `install-tools`は選択したツールの`install`文字列（`uv tool install --editable tools/...`や`cd tools/... && pnpm add -g .`）を**sourceのルートで**実行する。選択子は登録名（`aim`）またはリポジトリ相対の`path`（`tools/aim`）。**1つも指定しなければ全ツール**が対象なので、いきなり全件を走らせる前に`--dry-run`で内容を確認する
- **インストールはlocal sourceが必要。** コマンドがリポジトリ相対のため、GitHub sourceでは実行せずエラー（終了コード`4`）になる。cloneのパスは`config show`の`source.path`で確認できる
- あるツールのコマンドが非ゼロ終了すると、そこで停止し`install failed for <name> (exit N)`を出す。後続ツールは実行されない。失敗コマンド自体の出力はそのまま標準出力/標準エラーへ流れる
- このCLIが扱うのは列挙と実行だけ。`repo-tools.yaml`への登録や`install`文字列の修正はしない（SSOTは`repo-tools.yaml`自身）

## `workflow list` / `workflow show` — 目的から組み合わせを確認

```powershell
skill-tools workflow list
skill-tools workflow show microsoft-official-research
skill-tools workflow show multi-source-web-research --json
```

- `repo-workflows.yaml`をlocal sourceから読み、用途に応じたskill/toolの順序、optional/choice分岐、when/handoffを表示する。GitHub sourceでは非対応
- Workflowはcanonical `SKILL.md` IDと`repo-tools.yaml` keyを参照する。表示時にskillの`requires_skills`を再帰解決し、必要なtoolとenvironmentも表示する
- workflowが参照するskill closureについて、`requires_skills`は同じsource catalogにあるskill名だけ再帰解決する。catalog外の依存はsource外前提として対象に含めず、無関係なskillのcycleは表示に影響しない
- `--json`はworkflow listでは配列、showでは単一objectを返す。未知のworkflow ID・不正schema・unknown参照・重複ID・prerequisite cycleはエラー（終了コード`2`）
- list/showは参照表示だけで、外部API、installer、tool shell commandを実行しない

## `hooks` — エージェントフックの配置と登録

```powershell
skill-tools hooks list
skill-tools hooks list --agent codex --json
skill-tools hooks install --agent claude,codex nested_agents_md agent_sessions --dry-run
skill-tools hooks install --agent claude nested_agents_md
skill-tools hooks installed
skill-tools hooks update --dry-run
skill-tools hooks remove nested_agents_md --agent codex
```

- 対象はsourceの`repo-hooks.yaml`が指す`catalog.json`（agent-toolingのビルド生成物）。`repo-hooks.yaml`が無いsourceは「フック0件」でエラーにしない。`list`は`hook id<TAB>agents<TAB>summary`を出し副作用なし。`distributable: false`（このリポジトリ構造前提のフック）は`--all`を付けたときだけ出る
- エージェントは`claude` / `codex` / `cursor` / `antigravity` / `kilo`。`--agent`省略時は設定の`hooks.default_agents`、それも無ければ終了コード`2`。配置先・Claudeの登録先（`settings_file: project|local`）は`skill-tools.yaml`の`hooks.agents.<agent>`で変える
- `install`はファイル配置・seed設定（未存在時だけ）・登録ファイル（`.claude/settings.json` / `.codex/hooks.json` / `.cursor/hooks.json` / `.agents/hooks.json`。Kiloは無し）へのエントリ追加・manifest記録を1トランザクションで行う。**インストール＝有効化**で、無効化したいなら`remove`する
- **登録ファイルで書き換えるのはskill-toolsが追加したエントリだけ。** 利用者自身のエントリは保持する。同じフックファイルを実行する管理外エントリがあると二重発火の警告が出る（自動削除しない）ので、どちらを残すかユーザーに確認する
- `update` / `remove`は配置ファイルの変更・登録エントリの手編集をdriftとして中止する。`--force`の前に`--dry-run`で対象を確認する。seed設定は利用者が編集する前提なので追跡せず、`remove`でも消さない
- 配置後にフックが発火しない場合は、AIツールのセッション再起動を案内する

## `build-index` / `search` — 自然文でのスキル検索

```powershell
skill-tools build-index
skill-tools build-index --force
skill-tools search --query "ローカルでベクトル検索したい"
skill-tools search --query "ローカルでベクトル検索したい" --top 5 --json
```

- `search`は**保存済みsnapshotだけ**を見る。GitHub sourceでもbranchを取り直さないので、スキルを足した・変えた直後の結果が欲しいなら先に`build-index`を走らせる
- `build-index`が書くのはCLI専用のグローバルindexだけ。`skills-site`側のindexは読み書きしない（そちらを更新する目的でこのコマンドを使わない）
- **indexは既定で7日間キャッシュされる。** ただし各`build-index`実行時に登録スキルの本文hashと埋め込みmetadata hashを確認するため、変更は期間内でも反映される。変更が無く7日以内なら`Index is up to date: ...`を出し終了コード`0`で終わる。スキル追加・本文変更・metadata変更を反映するために`--force`は不要（日数を変えるなら`--max-age-days N`、`0`は常に再生成）
- 再生成が走っても全件を埋め込み直すわけではない。埋め込み対象は各スキルの`name`と`description`だけで、本文は埋め込みAPIへ送られず、name/descriptionが変わっていない行は前回のベクトルを再利用する。本文は指定index pathのローカルcacheにだけ保持される。本文サイズが1 MiBを超えるスキルは語彙検索対象外になりstderrに警告する。本文をcacheから破棄するにはindexファイルを削除する
- `search`はpure-Python BM25のUnicode語彙検索と既存の意味検索をRRFで統合する。JSONは`canonicalId`と一致語周辺の最大240文字の`snippet`を含み、tableにも`canonical_id`と`snippet`を表示する。本文全文やsnippetをrun logに記録しない。旧index schemaは`build-index`で再構築する
- **index未作成・APIキー未設定・別sourceのindexは非ゼロ終了**であり、空結果として扱わない。一方、fingerprint不一致とindexの古さはstderrの警告にとどまり検索は成功するので、警告だけを理由に`build-index`をやり直さない
- `--json`は`score` / `canonicalId` / `path` / `name` / `description` / `tool` / `plugin` / `status` / `snippet`を返す。`path`はlocalなら絶対パス、GitHubならblob URL、`canonicalId`はsource repo相対の`SKILL.md` path。table表示も`score` / `canonical_id` / `path` / `name` / `snippet`を含む。snippetは語彙一致がある場合だけ出る
- local sourceのファイル列挙は`git ls-files`（チェックアウト済みのサブモジュールの中も列挙する）。git管理下でないディレクトリではディレクトリ走査へフォールバックし、gitignoreを解釈しないぶん`config show`のfingerprint計算が遅くなる。install時のコピー対象はこの列挙に加えてバンドルコピーの除外/包含ポリシー（`tools/skill-tools/.gitignore`と`.skill-tools`）で絞られる

このリポジトリ内での作業開始時に「関連スキルを探してTODOへ組み込む」流れ自体は`discovering-skills`（`maintenance/plugin/skills/discovering-skills/`）が持つ。検索を手順の一部として回すならそちらに従い、このスキルはCLI単体の使い方として参照する。

## 終了コードの読み分け

| コード | 原因                                                                             | 次の一手                                                                                        |
| ------ | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `0`    | 成功                                                                             | —                                                                                               |
| `2`    | catalog / configuration / index                                                  | `config show`で採用設定とindexの状態を確認。index未作成なら`build-index`                        |
| `3`    | source（clone パス不正、GitHub取得失敗等）                                       | source設定・ネットワーク・refを確認                                                             |
| `4`    | install（skill・フックの配置失敗、`install-tools`のコマンド失敗・GitHub source） | 配置先の権限・既存ディレクトリ（rollback済み）、または`install`コマンドの出力・source種別を確認 |
| `1`    | その他（APIキー未設定など）                                                      | メッセージに従う。`search`系ならAPIキーを確認                                                   |

エラーメッセージは標準エラー出力へ`skill-tools: <理由>`の形で出る。非ゼロ終了を無視して後続処理へ進まないこと。

## 実行ログ

`skill-tools`は毎回の実行を、インストールされたパッケージ直下の`logs/`（このcheckoutでは`tools/skill-tools/logs/`）へ残す。`logs/input/0001.log`に実行CWDと引数、`logs/output/0001.log`にstdout / stderrと終了コードが同じ連番で入り、各アイテムの`run`マーカーで入力と出力が対応づく。**普段は`logs/input/`だけを眺めればよく**、対応する出力が要るときだけ同じ番号の`logs/output/`を開く。searchの結果はライブ表示するが、本文snippetを残さないよう`logs/output/`ではstdoutを`[search output redacted]`に置き換える。保存先は`SKILL_TOOLS_LOG_DIR`、ローテーション閾値（既定`1000000`バイト）は`SKILL_TOOLS_LOG_MAX_BYTES`、無効化は`SKILL_TOOLS_LOG_DISABLE=1`。ログはサイズのみでローテーションし、1回の実行の途中では分割しない。書き込み失敗はコマンドの結果・終了コードに影響しない。

## `--fb` — 使い方フィードバックを残す

スキル・ツール・workflowの使い方への不満、誤案内、抜け、紛らわしいエラーをユーザーが指摘したとき、またはエージェント自身がスキルの判断基準と実挙動のずれに気づいたときに使う。チャットに残すだけで終わらせず、次で保存する。

```powershell
skill-tools --fb <name> --fb-text "..."
echo "..." | skill-tools --fb <name>
```

- `<name>`はスキル名・ツール名・workflow ID。`--fb-kind`を省略すると3種すべてから探す。同名で曖昧なら保存せず終了コード`2`で候補が出るので、`--fb-kind skill|tool|workflow`か、スキルならcanonical IDで指定し直す
- ツールを使って出た不満は、スキルではなく**ツール名**宛てにする。スキルとツールのどちらの問題か迷ったら、直す対象のほうに残す
- 本文は`--fb-text`、またはパイプ（標準入力）。成功すると保存したファイルの絶対パスだけが出る
- 保存したFBを材料に、その場でスキル・ツールを自動改稿しない。残すことが先。FBフォルダの掃除・整理もこのスキルの仕事ではない
- 保存先は`skill-tools config show`の`fb.path`で確認できる。変えるときは設定の`fb.path`、または環境変数`SKILL_TOOLS_FB_DIR`（こちらが優先）

## やらないこと

- インストール・`config init`の代行（未導入なら`tools/skill-tools/README.md`を案内する）
- 設定ファイルへのAPIキーの書き込み（プロセス環境変数が常に優先。ソースcheckoutから実行するときだけ`tools/skill-tools/.env`）
- `ai-tools.yaml`への登録や`SKILL.md`の新規作成（別スキル・別手順の領分）
- `--source`等のoverrideを常用して設定ファイルの不備を隠すこと
