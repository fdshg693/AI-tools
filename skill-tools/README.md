# skill-tools

- 関連スキル
  - **tools\_plugin\my-tools\skills\skill-tools-cli\SKILL.md**
  - **maintenance\plugin\skills\discovering-skills\SKILL.md**

`skill-tools` は、`ai-tools.yaml` に登録された Agent Skill の一覧・配置・検索を一つの CLI にまとめたツールです。`maintenance/plugin/` のような未登録領域は対象にしません。目的別の組み合わせは `repo-workflows.yaml` の read-only catalog で確認できます。スキルの取得元（ローカル clone または GitHub）と CLI 専用インデックスの場所は、実行時の CWD から推測せず、設定ファイルで明示します。

source の SSOT yaml（`ai-tools.yaml`・`repo-tools.yaml`・`repo-workflows.yaml`・`repo-hooks.yaml`）は `registry/<name>` を先に探し、無ければ source ルートの `<name>` を読みます。yaml 内のパスはどちらでもリポジトリルート相対です。

同じ source（設定中の `source`）の `repo-tools.yaml` に登録された `tools/` 配下の first-class CLI ツールも、`list-tools` で列挙し `install-tools` でインストールコマンドを実行できます。`release` の値はここでは参照しません（タグ+GitHub Release の対象判定は別の関心事で、全エントリが列挙・インストール対象です）。

同じ source の `repo-hooks.yaml` が指すフックカタログ（agent-tooling が生成する `catalog.json`）から、Claude Code / Codex / Cursor / Antigravity / Kilo 向けのエージェントフックを `hooks list` で一覧し、`hooks install` でプロジェクト（既定は CWD、`--project-dir` で変更）またはユーザー全体（`--global`）へファイル配置と登録ファイル（`.claude/settings.json` / `.codex/hooks.json` 等）へのエントリ追加まで行えます。`hooks installed` / `hooks update` / `hooks remove` はスキルと同じ manifest で管理します。

## Install / update

ローカル clone を開発しながら使う場合:

```powershell
uv tool install --editable tools/skill-tools
```

clone なしで GitHub `main` から導入・更新する場合:

```powershell
uv tool install --force "git+https://github.com/fdshg693/AI-tools.git#subdirectory=skill-tools"
```

`uv tool install` 済みの CLI は `skill-tools self-update` で最新の GitHub 版へ更新できます（[`self-update`](#self-update) 参照）。

インストール後、グローバル設定ファイルを作成します。設定ファイルには埋め込み既定値が明記されるため、以後はこのファイルだけを編集すれば全プロジェクトの既定動作を変更できます。

```powershell
skill-tools config init
```

`OPENROUTER_API_KEY` はプロセスの環境変数で渡すか、ソース checkout から実行する場合だけ `tools/skill-tools/.env` に設定します。設定ファイルへ API key を書かないでください。プロセス環境変数が常に優先され、`site/skills-site/.env` や CWD の `.env` は読みません。

## Configuration

通常の設定は次の順でマージされます（後の層が優先されます）。

1. 組み込み既定値（GitHub `fdshg693/ai@main` と OS のキャッシュ領域）
2. グローバル設定（`%APPDATA%/skill-tools/skill-tools.yaml` または XDG 設定ディレクトリ）
3. プロジェクトの `skill-tools.yaml`（プロジェクト固有の上書き）。`--project-dir` を指定したときはそのディレクトリの、指定しないときは実行 CWD の `skill-tools.yaml` を読みます。どちらも無ければ読みません。`--project-dir` 指定時に CWD の yaml へ戻ることはありません（指定先を開いたときの設定と、入れた内容がずれないようにするため）

`--global` を指定したときは 1 と 2 だけを使い、プロジェクトの `skill-tools.yaml` は CWD のものも含めて読みません（どこから実行しても同じ結果にするため）。

`--config` と `SKILL_TOOLS_CONFIG` は明示的な単一設定ファイルとして扱い、上記のグローバル/プロジェクトのマージを行いません。`--project-dir` と併用したときも指定先の `skill-tools.yaml` は読まず、`config show` が `config.project: ... (not read: explicit config file)` と出します。プロジェクトの設定が無い場合はグローバル設定を使います。グローバル設定が削除されていても、埋め込み既定値で動作しますが、`config show` が警告を表示します。

CWD は「プロジェクトのルート（既定は CWD、`--project-dir` で変更）」の既定値としてだけ使い、カタログのリポジトリ位置の推測には使いません。source と index は設定に書いた値を解決します。

```yaml
source:
  type: local
  path: C:/src/ai

index:
  path: ~/.cache/skill-tools/skill-index.json

# Feedback directory. Omit to use the checkout's fb/ or the OS cache.
fb:
  path: ~/.cache/skill-tools/fb

# Canonical ID that `install-skills self` expands to (the default is shown).
self_skill: tools/_plugin/my-tools/skills/skill-tools-cli/SKILL.md

# Optional named install targets. Select one or more with `install-skills --target`.
targets:
  claude:
    destination: .claude/skills
  agents:
    destination: .agents/skills
skills:
  skills/plugins/coding/skills/testing/SKILL.md:
    destination: .agents/skills
    destinations:
      agents: .agents/custom-skills
```

`targets.<name>.destination` is the default for that named target. A skill-specific
`skills.<canonical-id>.destinations.<target>` overrides it; when `--target` is
omitted, the legacy `skills.<canonical-id>.destination` and default
`.claude/skills` behavior are unchanged. With a target selected, precedence is
target-specific skill destination, target default, legacy skill destination,
then `.claude/skills`.

`--global` でユーザー全体の場所（ホーム配下）へ入れるときの配置先は、ホーム相対の別の解決順で決まります。

```yaml
# --target を省略した --global の配置先（既定 .claude/skills）
global_destination: .claude/skills
targets:
  claude:
    destination: .claude/skills # global_destination が無ければ --global でもこの値
  antigravity:
    destination: .agents/skills
    global_destination: .gemini/config/skills # プロジェクトとユーザーで相対パスが違う target だけ書く
```

解決順は `targets.<name>.global_destination` → `targets.<name>.destination` → トップレベル `global_destination` → `.claude/skills` です（`--target` 省略時はトップレベル `global_destination` → `.claude/skills`）。`skills.<canonical-id>.destination(s)` はプロジェクト専用の上書きで、`--global` では使いません。値は `destination` と同じく安全な相対パスだけを受け付けます。`CLAUDE_CONFIG_DIR` などエージェント側の環境変数は見ないので、場所を変えている場合は `global_destination` を書きます。

`--global` の manifest・journal はホームの `.skill-tools/` ではなく、`SKILL_TOOLS_HOME/global`、無ければ Windows は `%LOCALAPPDATA%\skill-tools\global`、それ以外は `$XDG_STATE_HOME/skill-tools/global`（既定 `~/.local/state/skill-tools/global`）に置きます。index と違いキャッシュ領域ではないので、キャッシュを消してもグローバルに入れたスキルの管理情報は残ります。`config show --global` が `scope.state_dir` に場所を出します。

`self_skill` は `install-skills self` の展開先で、空でないリポジトリ相対パスです（絶対パスと `..` は不可）。`skills:` の中には置きません（`skills:` のキーは配置先上書き用の canonical ID だからです）。設定ロード時にファイルの存在は確認せず、実在は install 時にカタログから探します。見つからなければ `skill not found` で終了コード `2` になります。`config show` は解決済みの値を `self_skill:` に出し、`config init` が書くファイルにも既定値を明記します。

`source.type` は `local` または `github` だけです。`config init` が作成するグローバル設定では、source と index の既定値も省略せずに記載します。インデックスの既定保存先は Windows では `%LOCALAPPDATA%\skill-tools\skill-index.json`、XDG では `$XDG_CACHE_HOME/skill-tools/skill-index.json`、それ以外は `~/.cache/skill-tools/skill-index.json` です。`SKILL_TOOLS_HOME` または `index.path` で上書きできます。

使い方のフィードバック（`--fb`）の保存先は `fb.path` です。checkout または editable install（隣に `pyproject.toml` がある）では `<skill-tools プロジェクト>/fb`、wheel などで `pyproject.toml` が同梱されないときは OS キャッシュ領域の `skill-tools/fb`（`SKILL_TOOLS_HOME` を含む）が既定です。優先順は環境変数 `SKILL_TOOLS_FB_DIR`、設定の `fb.path`、既定値です。設定ファイル内の相対パスは、その設定ファイルのあるディレクトリ基準で解決します（`index.path` と同じ）。実行ログの `logs/` とは別のディレクトリです。

`source.type: local` のファイル一覧は `git ls-files --cached --others --exclude-standard` で取得します。チェックアウト済みのサブモジュールは、その中でも同じ `git ls-files` を実行し、サブモジュールのパスの下のファイルとして数えます（未初期化のサブモジュールの中身は見えません。アンブレラでは `just sub-init` を先に実行します）。対象が git 管理下でない（`.git` が無い、git が使えない等）場合はディレクトリ走査へフォールバックし、その際は `.git` / `.venv` / `venv` / `node_modules` / `__pycache__` / `.mypy_cache` / `.pytest_cache` / `.ruff_cache` / `.tox` / `.codegraph` / `.pnpm-store` / `.turbo` / `.next` / `.astro` を除外します。フォールバックは gitignore を解釈しないため、fingerprint 計算（`build-index` など）が git 管理下より遅くなります。`config show` は fingerprint を再計算しません。

フックのインストール先は `hooks:` で上書きできます（すべて任意）。

```yaml
hooks:
  default_agents: [claude, codex] # `hooks install` で --agent を省略したときの対象
  agents:
    claude:
      destination: .claude/hooks # フックファイルの配置先（プロジェクト相対）
      settings_file: project # project=.claude/settings.json / local=.claude/settings.local.json
    codex:
      destination: .codex/hooks
      global_destination: .codex/hooks # --global の配置先（ホーム相対）
  install: # `hooks sync` が揃える、エージェントごとの入れるフック id
    claude: [nested_agents_md, agent_sessions]
    codex: [nested_agents_md]
```

| agent       | 既定の配置先     | 登録ファイル                                                   | 登録するコマンド                                                                    |
| ----------- | ---------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| claude      | `.claude/hooks/` | `.claude/settings.json`（`settings_file: local` で `.local`）  | `command` + `args`（`${CLAUDE_PROJECT_DIR}/<dir>/<file>`）                          |
| codex       | `.codex/hooks/`  | `.codex/hooks.json`                                            | `command`（`git rev-parse --show-toplevel` 基準）+ PowerShell 用 `commandWindows`   |
| cursor      | `.cursor/hooks/` | `.cursor/hooks.json`（`version: 1`）                           | プロジェクトルート相対（matcher はエントリ内）                                      |
| antigravity | `.agents/hooks/` | `.agents/hooks.json`（フック id をケバブケースにしたキー配下） | プロジェクトルート相対。matcher があるイベントだけ `{matcher, hooks: [...]}` で包む |
| kilo        | `.kilo/plugin/`  | なし                                                           | 配置だけで有効（TS プラグインが隣の Python を起動）                                 |

`--global` では次の場所を使います。`settings_file: local` と `destination` はプロジェクト専用で無視し、配置先は `hooks.agents.<agent>.global_destination`（ホーム相対）で変えられます。

| agent       | `--global` の配置先       | 登録ファイル                  | 登録するコマンド                                                                                         |
| ----------- | ------------------------- | ----------------------------- | -------------------------------------------------------------------------------------------------------- |
| claude      | `~/.claude/hooks/`        | `~/.claude/settings.json`     | `command` + `args`（配置したファイルの絶対パス。`uv-project` の `--project` もホームの絶対パス）         |
| codex       | `~/.codex/hooks/`         | `~/.codex/hooks.json`         | 絶対パスを POSIX の `command` は `'...'`、PowerShell の `commandWindows` は `'...'`（`'` は `''`）で囲む |
| cursor      | `~/.cursor/hooks/`        | `~/.cursor/hooks.json`        | `~/.cursor/` 相対（`hooks/<file>`）。配置先を `.cursor/` の外にしたときは絶対パス                        |
| antigravity | `~/.gemini/config/hooks/` | `~/.gemini/config/hooks.json` | 絶対パスの `type` + `command`。キーはフック id のケバブケース。matcher があるイベントだけグループで包む  |
| kilo        | `~/.config/kilo/plugin/`  | なし                          | 配置だけで有効                                                                                           |

- 絶対パスはインストール時に1回だけ計算してエントリに書きます（パスは `/` 区切り）。Windows で入れた Codex のエントリは POSIX 側の `command` にも Windows のパスが入ります。ホームの場所が変わったら `hooks update --global` で入れ直します。
- `distributable: false` のフックは `--global` では常に終了コード `2` です。ユーザー全体の場所が無いエージェントを `--agent` で指定したときも終了コード `2`、`hooks.default_agents` 経由なら警告して飛ばします。
- **`~/.claude/settings.json` は実行中の Claude Code 自身も書き換えます。** skill-tools は登録ファイルを書く直前に読み直し、読んでから内容が変わっていれば何も書かずに終了コード `4` で止まります。Claude Code を閉じてから実行し、ファイル全体が整形し直されるので先に `--dry-run` で確認してください。
- プロジェクトと `--global` の両方に同じフックを入れると二重に発火します。二重発火の警告は1つの登録ファイルの中しか見ないので、この組み合わせは検出しません。どちらか一方に入れてください。

カタログの `runner` が `python` なら `python <file>`（Windows）または `python3 <file>`（それ以外）、`uv-script`（PEP 723）なら `uv run --script <file>`、`uv-project` なら `uv run --project <project root> <file>` で起動します。Python の起動名は `hooks install`／`hooks update` を実行した OS で決まり、登録ファイルに OS 別の欄を持つ Codex だけは常に POSIX 側 `python3`・`commandWindows` 側 `python` の両方を書きます。別の OS へ移ったら、その端末で `hooks update` すると古い登録（manifest の hash で特定）が消えて新しい起動名で登録し直されます。

設定例は [skill-tools.yaml.example](skill-tools.yaml.example) を参照してください。

### リンク方式（`--mode link`）とストア

`install-skills` の配置方式は `copy`（既定。プロジェクトにスキルをコピーする）と `link` の 2 つです。`link` では、skill-tools が管理するグローバルな置き場（ストア）にスキルを 1 回だけコピーし、プロジェクトの配置先（`.claude/skills/<name>` など）にはストアを指すリンクを置きます。リンクは Windows では Junction（管理者権限も開発者モードも不要）、それ以外ではディレクトリの symlink です。ストアを更新すると、そこを指す全プロジェクトが最新に追従します。ユーザー全体（`--global`）には入れたくないが多くのプロジェクトで使うスキルを、常に最新のまま配るための方式です。

```yaml
# install-skills で --mode を省略したときの方式（既定 copy）
install_mode: copy

store:
  path: ~/skill-store # 省略時は下記の既定の場所。相対パスはこの設定ファイル基準
```

- 方式は `--mode copy|link`、省略時は設定の `install_mode`、それも無ければ `copy` です。`install_mode` が `copy`／`link` 以外なら終了コード `2` です。target ごと・スキルごとの方式の指定はありません。
- `--global` は常にコピーです。`--mode link --global` は終了コード `2`、設定の `install_mode: link` で `--global` を実行したときは stderr に注記を出してコピーします（ユーザー全体の置き場は 1 か所なので、リンクにする利点がないため）。
- ストアの既定の場所は `SKILL_TOOLS_HOME/store`、無ければ Windows は `%LOCALAPPDATA%\skill-tools\store`、それ以外は `$XDG_STATE_HOME/skill-tools/store`（既定 `~/.local/state/skill-tools/store`）です。`--global` の管理情報と同じく、キャッシュ領域には置きません（キャッシュを消すと全プロジェクトのリンク先が消えるため）。`config show` が `store.path` と `install_mode` を出し、`config init` が書くファイルにも既定値を明記します。
- ストアは「source（local のパス、または GitHub の owner/repository/ref）× canonical ID」ごとに最新の 1 つだけを持ち、`<store>/<source key>/<canonical ID の hash>/<スキル名>` に置きます。版を分けないので、古い版を指し続けるリンクはできません。ストア自体の manifest・journal は `<store>/.skill-tools/` にあり、どのプロジェクトのどのパスがどの entry にリンクしているかを `<store>/.skill-tools/referrers.json` に記録します。
- リンク先は常にストアのコピーで、local source の checkout を直接は指しません（バンドルコピーの除外/包含ポリシーを効かせ、開発途中の変更をそのまま見せないため）。

**リンクにする前に知っておくこと**

- **リンクしたスキルのファイルを編集すると、ストアのコピーが変わり、そこを指す全プロジェクトに効きます。** さらにストアの drift として扱われ、次の `update-skills`／`store update` は `--force` なしでは止まります。プロジェクトだけで手を入れたいスキルは `copy` にします。
- **リンクにした配置先は `.gitignore` に入れてください。** Git for Windows は Junction をふつうのディレクトリとして扱い、`git add -A` でリンク先の中身を通常のファイルとしてコミットしてしまいます。Windows 以外の symlink はリンク先の絶対パスとして記録され、他の環境では壊れたリンクになります。skill-tools は `.gitignore` を編集しません。
- **リンクのスキルを読まないエージェントや版があります。** Claude Code は Windows の Junction のスキルを読みます（確認済み）が、symlink のスキルディレクトリを読まない不具合の報告がまだ open です（主に macOS/Linux）。Codex・Cursor・Kilo Code は修正済みと報告されています。Antigravity はリンクのスキルを読まない報告があります。スキルが一覧に出なければ `install-skills --mode copy --overwrite <skill>` でコピーに戻します。
- **Windows では、リンク経由でストアのファイルを開いているプロセスがあるとストアを更新できません。** 更新は置き場の名前の入れ替えで行うため、エディタやエージェントがスキルのファイルを開いていると失敗します（終了コード `4`。途中の変更は戻されます）。それらを閉じてから再実行します。
- **`store.path` を変えると既存のリンクは古いストアを指したままになり、新しいストアの設定では `update-skills` が止まります。** 移行は、各プロジェクトで `remove-skills <skill>` → 設定を変更 → `install-skills --mode link <skill>` と入れ直し、最後に古いストアを指す設定で `store gc` を実行して古いストアを片付けます（参照元が分からない場合は `store list --json` の `referrers` を見ます）。

### `repo-tools.yaml` の `description` locator

source の `repo-tools.yaml` の各エントリは、`description` にそのツールの概要の取得元を `<repo相対path>[#<dotted key>]` の1文字列で書けます（例: `tools/llm/aim/pyproject.toml#project.description`）。path は `repo-tools.yaml` からの相対で、`install` と同じ基準です。形式は拡張子で決まり、`.toml` / `.json` / `.yaml` / `.yml` は `#key` が必須でその値を、それ以外はプレーンテキストとして最初の見出し行（先頭の YAML frontmatter は読み飛ばす）を概要にします。`#key` はドット区切りでテーブルや配列を辿れます。locator 未指定のエントリは概要を空で表示し、ファイル・key・型が壊れているときは `list-tools` がエラーで止まります。

### バンドルコピーの除外/包含ポリシー

`install-skills` が skill をコピーするときは、上記のファイル一覧（`git ls-files` / git 無し時のディレクトリ走査）に加えて、次の順で**一方向に**判定します。適用範囲は全スキル共通で、プラグインやスキル単位の設定はありません。

1. **組み込みの既定除外** — `.git/` / `.venv/` / `venv/` / `node_modules/` / `__pycache__/` / `.mypy_cache/` / `.pytest_cache/` / `.ruff_cache/` / `.tox/` / `.codegraph/` / `.pnpm-store/` / `.turbo/` / `.next/` / `.astro/` と `.env`（大文字小文字を問わない）
2. **source の `tools/skill-tools/.gitignore`** — gitignore 構文（`**`・`!` 否定・末尾 `/` のディレクトリ指定）をそのまま評価
3. **source の `tools/skill-tools/.skill-tools` の `include:`** — 上書きの最終段。既定除外や `.gitignore` で外れたファイルを復帰させる

GitHub source にも 1〜3 の判定を適用しますが、include による**追加取得**（後述）はローカルだけです。

`.skill-tools` の出荷時の `include:` は `uv.lock` のみです。スキルに同梱した CLI を `uv run --project` で揃えるスキル（`skills/plugins/web-lookup/skills/web-lookup` 等）が、依存を固定するために commit している lockfile を残すためで、`tools/skill-tools/.gitignore` の `uv.lock` 除外を打ち消します。

**`.env` は既定で除外したまま**です。スキルの `.env` をコピーさせたい場合だけ、利用者が `.skill-tools` の `include:` に明示的に追加します（登録例は同ファイルにコメントで記載）。指定すると秘密情報がコピーされる点を理解した上で使ってください。

`include:` に指定したファイルが git 管理外（`.env` など）の場合、ローカル source ではディスクを直接走査して救済します。この走査は既定除外ディレクトリ（`.venv/` 等）を枝刈りするため、その中までは復帰できません。GitHub source は commit 済みファイルしか取得できないため、include はツリー上のファイルにだけ効きます。

ポリシーファイルは source の `tools/skill-tools/` 直下から読みます。別リポジトリなどでこの2ファイルが無い場合は既定除外だけで動作します。一方、ファイルが存在するのに読めない（ネットワーク・レート制限）・YAML が壊れている・未知のキーがある場合はエラーで停止します（不在と取得失敗を区別するため）。

## Commands

```powershell
skill-tools config init
skill-tools config show --config C:\src\ai\tools\skill-tools\skill-tools.yaml.example
skill-tools --fb alpha --fb-text "検索結果の並びが期待と違った"
skill-tools --fb tools/llm/aim --fb-kind tool --fb-text "install の説明が足りない"
Get-Content feedback.txt | skill-tools --fb sample-flow --fb-kind workflow
skill-tools list-skills --source local --repo C:\src\ai
skill-tools workflow list
skill-tools workflow show microsoft-official-research
skill-tools install-skills --source local --repo C:\src\ai alpha
skill-tools install-skills --target claude,agents alpha
skill-tools install-skills self
skill-tools installed-skills --json
skill-tools install-skills --project-dir C:\src\other-project alpha
skill-tools installed-skills --project-dir C:\src\other-project
skill-tools install-skills --global --dry-run alpha
skill-tools install-skills --global alpha
skill-tools installed-skills --global
skill-tools update-skills --global
skill-tools remove-skills --global alpha
skill-tools config show --global
skill-tools install-skills --mode link --dry-run alpha
skill-tools install-skills --mode link alpha
skill-tools store list
skill-tools store update --dry-run
skill-tools store gc --dry-run
skill-tools update-skills alpha --dry-run
skill-tools remove-skills alpha --dry-run
skill-tools install-skills --source github --dry-run alpha
skill-tools list-tools
skill-tools list-tools --json
skill-tools install-tools --dry-run
skill-tools install-tools aim tav
skill-tools hooks list
skill-tools hooks list --agent codex --json
skill-tools hooks list --all
skill-tools hooks install --agent claude,codex nested_agents_md agent_sessions --dry-run
skill-tools hooks install --agent claude nested_agents_md
skill-tools hooks installed
skill-tools hooks install --project-dir ..\other-project --agent claude nested_agents_md
skill-tools hooks install --global --agent claude,codex nested_agents_md --dry-run
skill-tools hooks installed --global
skill-tools hooks update --dry-run
skill-tools hooks remove nested_agents_md --agent codex
skill-tools hooks sync --dry-run
skill-tools self-update --dry-run
skill-tools self-update
skill-tools build-index --source local --repo C:\src\ai
skill-tools build-index --force
skill-tools search --query "ローカルでベクトル検索したい"
skill-tools search --query "ローカルでベクトル検索したい" --top 5 --json
```

通常利用では `--source` を毎回付けず、`skill-tools.yaml` に source を書いてください。`--source` / `--repo` / `--github-*` / `--index-path` は CI と移行用の override です。

- `--fb <name>` はサブコマンドと併用しない、書き込み専用の入口です。`<name>` はスキル名または canonical ID、`repo-tools.yaml` の登録キーまたはリポジトリ相対 path、`repo-workflows.yaml` の id です。`--fb-kind skill|tool|workflow` を省略すると3種すべてから探し、2件以上一致したら保存せず終了コード `2` で候補を `kind: id`（skill は canonical ID）として出します。0件も終了コード `2` で、`list-skills` / `list-tools` / `workflow list` を案内します。`--fb-text` を省略すると本文は標準入力です。本文が空なら終了コード `1` で保存しません。成功時は保存したファイルの絶対パスだけを標準出力に出します。`--config` / `--source` / `--repo` / `--github-*` は `list-skills` と同じようにカタログを選びます。`OPENROUTER_API_KEY` は不要です。`workflow` コマンドは local source 限定ですが、`--fb` の workflow 名は `repo-workflows.yaml` の id だけを読むので GitHub source でも解決できます。
  - 保存先は `<fbルート>/skills|tools|workflows/<対象名>/<YYYYMMDD-HHMMSS>-fb.md` です。対象名はスキル名、ツールの登録キー、workflow id です。時刻は UTC で、同一秒の衝突は `-2`, `-3` を id 側に付けます（`20260913-123456-2-fb.md`）。本文はそのまま書き、frontmatter は足しません。作成は排他的で、既存ファイルは上書きしません。
  - パスに使う対象名はカタログで解決できた値だけです。`[A-Za-z0-9._-]` 以外や `..` を含む名前は保存せず終了コード `2` です。
  - 種別を省略したとき、1種別のカタログが壊れていても他種別の一致は保存できます。`--fb-kind` で指定した種別が壊れているときはそのエラーで止まります。
- `list-skills` は `source path<TAB>skill name<TAB>file count` を標準出力へ出し、解決済み source を stderr に出します。source path は local なら SKILL.md の絶対パス、GitHub なら `https://github.com/<owner>/<repo>/blob/<commit>/<path>` です。
- `install-skills` は config の source から bundle を全件 staging してから配置します。選択子は source path・リポジトリ相対の canonical ID・一意な skill 名のいずれかです。既存 skill は `--overwrite` なしでは変更しません。`--dry-run` はコピーしません。コピー対象はバンドルコピーの除外/包含ポリシーで絞り込まれ、`.venv` などの生成物や `.env` は既定で同梱されません。
  - 選択子がカタログに無く、それが source 内に実在する `SKILL.md` のパス（canonical ID、または local source の絶対パス）なら、`skill not found: <選択子> (<canonical ID> exists in the source but is not registered in ai-tools.yaml, ...)` と出します（終了コード `2`）。名前での指定は未登録の領域を探しません（source 全体の走査と同名の誤検出を避けるため）。
  - プロジェクトへ入れるとき（`--global` でないとき）、同じスキル名がグローバルの manifest にあれば `warning: <name> is also installed user-wide (~/...); agents may load both copies` を stderr に出して続行します（`--dry-run` も同じ）。読むのはグローバルの manifest だけで、`~/.claude/skills` の走査や、プラグイン経由の重複は確かめません。
- `install-skills --target name[,name...]` は選択bundleを指定された全targetへ配置します。target名は `skill-tools.yaml` の `targets` に定義し、destinationはproject相対の安全なパスにします。すべてのtargetを事前検査し、installはproject単位lock内でpathを再検証してからstage・replaceします。`--dry-run` はsource、canonical ID、target名、最終相対pathをtargetごとに表示します。`--target`省略時は従来の単一destination動作です。
- `--project-dir <path>` は `install-skills` / `installed-skills` / `update-skills` / `remove-skills`、`hooks install|installed|update|remove`、`config show` に付けられ、配置・管理するプロジェクトのルートを CWD から変えます。manifest・journal もそのルートの `.skill-tools/` を使い、設定はそのルートの `skill-tools.yaml` を重ねます（上記 Configuration）。相対パスは実際の CWD 基準で解決し、Junction・シンボリックリンクは実体へ解決します。存在するディレクトリだけを受け付け（作りません）、無ければ終了コード `2` です。`--repo` / `--index-path` / `--config` の相対パスも、これまでどおり実際の CWD 基準です。`list-skills` などの配置先を持たないコマンドには付きません。
- `--global` は `install-skills` / `installed-skills` / `update-skills` / `remove-skills`、`hooks install|installed|update|remove` と `config show` に付けられ、ユーザー全体の場所（ホーム配下。スキルの既定は `~/.claude/skills/<name>`、フックは上記 Configuration の表）へ配置・管理します。`--project-dir` とは同時に指定できません（終了コード `2`）。配置先と manifest の場所は上記 Configuration を参照してください。`--dry-run` や update/remove の表示は `~/.claude/skills/alpha` のようにホームからのパスで出します。manifest の local source は常に絶対パスで記録します。
- `install-skills` 成功時は、管理情報をプロジェクトのルートの`.skill-tools/manifest.json`へ記録します。manifestはschema version、canonical ID、bundle名、target/destination、project-relative install path、source descriptor、配置ファイルごとのSHA-256を持ちます。絶対install pathは保存せず、manifestや`.gitignore`の共有・管理方法も強制しません。
- `install-skills self` は、予約語 `self` を設定の `self_skill`（skill-tools を使うコンパニオンスキルの canonical ID）へ展開して通常の install と同じ経路で配置します。既定値は `tools/_plugin/my-tools/skills/skill-tools-cli/SKILL.md` で、`--dry-run` / `--overwrite` / `--target` もそのまま使えます。`self` はカタログ上の同名スキルより優先されるため、同名のスキルを入れたいときは canonical ID を渡します。`install-skills self other-name` は両方を入れ、引数なしの `install-skills` は全件インストールにならずエラーです。
- `install-skills --mode link` は、まずストアに entry が無ければコピーし（あればそのまま使い、更新はしません）、参照元を記録してから、プロジェクトの配置先にリンクを置いて manifest に記録します。ストアとプロジェクトは別のトランザクションで、ストアの後にプロジェクトを処理します。出力の各行の末尾に `(link -> <ストアの entry の絶対パス>)` が付きます（`--dry-run` も同じ）。既存の配置先は `--overwrite` なしでは変えず、`--overwrite` を付ければコピーとリンクを互いに置き換えられます。リンクをコピーで置き換えても、ストアの entry は消えず参照元の記録だけが消えます。
- `installed-skills` はsource・catalog・networkを参照せず、manifest記録を一覧します。TSV の列は `canonical_id<TAB>target<TAB>install_path<TAB>source<TAB>mode` で、`mode` は `copy` か `link` です（既存の列位置は変えていません）。TSV の `source` 列は、manifest にプロジェクト相対で記録した local source のパスも絶対パスに解決して出します（`hooks installed` も同じ。manifest の保存形式は変えません）。`target` 列は `--target` なしで入れた entry では `(default)` です。`--json`でmanifest entryの配列を記録どおりに出力し、各 entry は `mode` を、リンクの entry は `store`（ストア相対の entry の位置）も持ちます。
- `update-skills` はリンクの entry について、プロジェクトではなくストアの entry を更新します。**同じスキルにリンクしている他のすべてのプロジェクトにも効きます**。出力の末尾に `(shared: store entry <path> has N link(s))` と参照元の数を出すので、`--dry-run` で影響範囲を確認してください。1 つのストアの entry を指すリンクが複数あっても更新は 1 回です。リンクが設定の `store.path` 以外のストアを指していると止まります（終了コード `4`）。`remove-skills` はリンクだけを消し、ストアの entry は残します（`(link only; the shared store entry is kept)`）。消えたリンクの entry は `store gc` で回収します。
- `store list [--json]` はストアの entry を `store_path<TAB>canonical_id<TAB>links<TAB>source` で一覧します（`links` は記録されている参照元の数で、リンクが実在するかはここでは確かめません）。`--json` は `{storePath, path, canonicalId, bundleName, source, referrers: [{projectRoot, installPath}]}` の配列です。ストアの場所は stderr に出します。
- `store update [skill...] [--dry-run] [--force]` は、プロジェクトを経由せずにストアの entry を設定中の source から更新します（そこを指す全プロジェクトに効きます）。選択子は canonical ID・スキル名・ストア相対のパスで、省略すると全 entry が対象です。source が設定と異なる entry は、選択したなら終了コード `4`、省略時は警告して飛ばします。ストアの entry を手で編集していれば drift として止まり、`--force` で置き換えます。
- `store gc [--dry-run]` は、参照元の記録を確かめ直し、プロジェクトのそのパスがもうその entry へのリンクでない記録を消してから、記録が 1 件も残らない entry を削除します。リンクが作られる前の記録を消さないよう、作られてから 1 時間以内でパスがまだ存在しない記録は残します。ストアの entry が drift していれば削除せずに止まります。`store` サブコマンドは `--config` / `--source` などで設定を選び、`--project-dir` / `--global` は付きません（ストアはプロジェクトに属さないため）。実行ログにはパスとスキル ID だけが残ります。
- `update-skills [skill...]` はmanifest記録を起点に、同じsource identityのentryだけを更新します。GitHubは同じowner/repository/refを再解決します。選択したentryのsourceが設定と異なる場合は暗黙切替を拒否し、catalogから消えたskillは警告して配置を保持します。`remove-skills [skill...]` はsource・catalog・network不要で、manifest entryのみを対象にします。選択子はcanonical ID、bundle名またはproject-relative install pathです。
- `update-skills` は、source のバンドル（バンドルコピーの除外/包含ポリシーを通した後のファイル集合）の hash が manifest の記録（リンクの entry はストアの entry の記録）とすべて同じ entry を `unchanged` と出し、書き換えません（`--dry-run` も同じ。`hooks update` と同じ表示）。GitHub source で commit だけが進んで中身が同じときも書き換えないので、manifest の `commit` は前回の値のままです。`--force` で drift を戻すときは、中身が同じでも `update` になります。
- `update-skills` / `remove-skills` は既定で配置済みファイルのhash、欠落・追加file、symlinkを検証し、driftがあれば変更を中止します。エラーは `managed installation has drifted: <path> (modified: SKILL.md; missing: ...; extra: extra.txt)` のように、変更・欠落・余分のファイルを配置先相対ですべて列挙します。`--force`は対象managed directory内の変更・追加fileを置換または削除し得る破壊的操作です。実行前に`--dry-run`で対象を確認してください。manifest外のdirectoryは`--force`でも探索・削除しません。
- `list-tools` は source の `repo-tools.yaml` に登録されたツールを `tool name<TAB>path<TAB>install command<TAB>summary` の4列で標準出力へ出し、解決済み source を stderr に出します。`path` は local なら絶対パス、GitHub ならツールフォルダの blob URL です。`summary` は各エントリの `description` locator を解決した1行概要で、locator 未指定なら空文字です。locator が壊れている（ファイル無し・key 無し・型不一致）ときはツール名と locator を示して終了コード `2` で止まります。`release` の値で絞り込まず、全エントリを出します。`--json` を付けると `{name, path, install, description}` の配列を `json.dumps(..., indent=2)` で出します（stderr の `source: ...` は TSV と同じく出ます）。
- `install-tools` は選択したツールの `install` コマンドを source のルートで実行します。選択子は登録名またはリポジトリ相対の `path` で、1つも指定しなければ全ツールが対象です。`--dry-run` はコマンドを表示するだけで実行しません。実行は**local source が必要**で、GitHub source ではエラーになります（コマンドがリポジトリ相対のため）。あるツールのコマンドが非ゼロ終了した時点で停止し、そのツール名と終了コードを報告します。
- `workflow list` / `workflow show <id>` は local source の `repo-workflows.yaml` を読み、目的・順序付きstep・optional/choice分岐・handoffと、canonical skill ID / `repo-tools.yaml` keyから解決したskill prerequisite・tool・environment要件を表示します。GitHub sourceでは非対応です。list/showは外部API、installer、tool shell commandを実行しません。
- workflowが参照するskill closureについて、`requires_skills`は同じsource catalogで一意に見つかるskillだけ再帰解決します。catalog外のskill依存はsource外前提として解決対象に含めず、無関係なskillのcycleはworkflow表示に影響しません。
- `hooks list` は source の `repo-hooks.yaml` → `catalog.json` を読み、`hook id<TAB>agents<TAB>summary` の3列を標準出力へ、解決済み source を stderr へ出します。副作用はありません。GitHub source でもリポジトリ直下の `repo-hooks.yaml` とカタログの2ファイルを取得するだけで一覧できます。`repo-hooks.yaml` が無い source は「フック0件」（`(no hooks)`）で、エラーにしません。`distributable: false`（このリポジトリ構造が前提のフック）は既定で表示せず、`--all` で summary 末尾に `(not distributable)` を付けて表示します。`--agent claude|codex|cursor|antigravity|kilo` でそのエージェント向けのフックだけに絞り、`--json` では `{id, description, distributable, requiresTools, agents}` の配列（`agents` は `--agent` 指定時その1つだけ、ファイルパスは source 相対）を出します。カタログの検証は厳格で、未知キー・不正なパス・カタログが参照するのに source に無いファイルは終了コード `2` で止まります。フックカタログはスキルのカタログと独立しており、壊れていても `list-skills` / `install-skills` などスキル系コマンドには影響しません。
- `hooks install [--agent a,b] <hook-id>...` は選んだフック×エージェントごとに、(1) カタログの配布ファイルを配置先へコピー、(2) seed 設定（`config/<id>.yaml` 等）を**未存在時だけ**配置、(3) 登録ファイルへエントリを追加、(4) manifest へ記録、を1トランザクションで行います。`--agent` 省略時は `hooks.default_agents`、それも無ければ終了コード `2`。フックが一部の agent に非対応ならその agent を警告して飛ばし、どれにも対応しなければエラーです。配置先に manifest 管理外の同名ファイルがあれば `--overwrite` 無しでは止まり、同じフック×エージェントが既に管理下なら `hooks update` を案内して止まります。`--dry-run` は配置・登録予定を `would install` / `would seed` / `would register` で表示するだけです。
  - `distributable: false` のフックは、local source のパスがプロジェクトルート（既定は CWD、`--project-dir` で変更）と同じとき、つまりそのリポジトリ自身への自己インストールでだけ入れられます（それ以外と `--global` は終了コード `2`）。
  - `requiresTools` のツールが PATH に無ければ、`skill-tools install-tools <name>` を案内する警告を出して続行します。
  - 登録ファイルに manifest 管理外で同じフックファイルを実行するエントリがあれば「二重発火し得る」と警告します（自動削除はしません）。
  - GitHub source からも入れられます（配布物は commit 済みの generated ファイルで、コマンドは実行しません）。
- 登録ファイルの編集は skill-tools が追加したエントリだけが対象です。追加エントリの正規化 JSON の SHA-256 を manifest に記録し、remove/update はその hash と一致するエントリだけを消します。Claude/Codex は同じ event・matcher のグループがあればその `hooks[]` 末尾に追記し、無ければグループを新設します。削除で空になったグループ・event キー・ファイルは消します。利用者自身のエントリの順序・内容と未知キーは保持しますが、**ファイル全体をインデント2の JSON で書き直すため整形差分が出ます**。コメント付き（JSONC）など JSON として読めない登録ファイルは編集せずエラーで止まります。
- `hooks installed [--json]` は manifest の `hooks` 記録を `hook_id<TAB>agent<TAB>install_dir<TAB>registered_in<TAB>source` で一覧します（source・network 不要）。
- `hooks update [<hook-id>...] [--agent a,b]` は同じ source identity の記録だけを、旧エントリの削除と新エントリの追加を1トランザクションにして更新します（配置先は記録どおり、登録ファイルは現在の設定に従う）。変更の無いものは `unchanged` と表示します。source 切替の拒否・カタログから消えたフックの保持はスキルの `update-skills` と同じです。`hooks remove [<hook-id>...] [--agent a,b]` は source・config 不要で、記録されたファイルと登録エントリだけを消します。どちらも選択子なしなら全管理フックが対象です。
- `hooks sync [--dry-run] [--overwrite] [--force]` は設定の `hooks.install.<agent>` を「入れたいフックの一覧」として、管理フックをそれに揃えます。列挙されていて未管理のものを `hooks install` と同じ手順で入れ、manifest にあって列挙から外れたもの（列挙に無いエージェントの分も含む）を `hooks remove` と同じ手順で消します。どちらも 1 トランザクションです。すでに管理下のフックは触らないので、中身の更新は `hooks update` で行います。`hooks.install` が無い・空のときは終了コード `2` です。`--overwrite` は新しく入れるフックに、`--force` は消すフックの drift に効きます。`--global` でも使え、そのときはユーザー全体の場所が無いエージェントを警告して飛ばします。リポジトリでは入れるフックの一覧を gitignore した設定ファイルに書き、コミットするのはサンプルだけにする、という使い方を想定しています。
- `hooks update` / `hooks remove` は既定で drift（配置ファイルの変更・欠落、登録エントリの手編集・削除）があれば中止します。`--force` は変更されたフックファイルを置換・削除し、見つからない登録エントリは警告してスキップします。seed 設定は利用者が編集する前提なので hash 追跡せず、`remove` でも消しません。
- <a id="self-update"></a>`self-update [--dry-run]` は skill-tools **自身**を更新します（スキル更新の `update-skills` とは別物）。インストール元は配布メタデータの `direct_url.json`（PEP 610）で判定します。
  - **editable install**（`dir_info.editable`）は何もせず、ローカル clone で `git pull` するよう案内して終了コード `0` で終わります。
  - それ以外は `uv tool install --force "git+<URL>#subdirectory=<dir>"` を実行します。以前 git からインストールしていれば、その URL・`@<branch/tag>`・subdirectory を引き継ぎ、そうでなければ既定の GitHub `fdshg693/AI-tools`（subdirectory `skill-tools`）を使います（branch 未指定なら既定ブランチの最新）。`tools/` がサブモジュール `AI-tools` になる前にアンブレラ `fdshg693/ai` の `tools/skill-tools` から入れた環境は、既定の `AI-tools` へ切り替えます。
  - `uv tool install` で入れた環境（`uv-receipt.toml` がある）でなければ、終了コード `4` で中止します。`uv` が PATH に無い場合も同様です。
  - Windows では実行中の `skill-tools.exe` を自分自身で置換できないため、更新は本コマンド終了後に別プロセスで始まり、進捗は一時ディレクトリの `skill-tools-update.log` に出ます。完了後に `skill-tools --version` で確認してください。
  - `--dry-run` は実行予定のコマンドを表示するだけです。
- `build-index` は CLI 専用の global index だけを書き、`skills-site` 側の index は読み書きしません。既定では7日間の鮮度ゲートがあり、登録スキルの検索本文hashと埋め込みmetadata hashが変わっていない場合に再生成をスキップします（後述）。
- `search` は保存済み snapshot だけを検索します。GitHub source でも branch を再取得しません。index 未作成・API key 未設定・別 source の index は非ゼロ終了です。fingerprint 不一致とインデックスの古さは stderr の警告にとどめ、検索自体は成功します。
  - local source では、結果の canonical ID が今の source のカタログ（`ai-tools.yaml` に登録されたスキル）に無ければ、`warning: N of M result(s) are not in the source's current catalog ...; run skill-tools build-index` を stderr に出します。古さの警告とは別で、作って間もない index でもスキルの移動・登録解除の後なら出ます。結果からは落とさず index の値をそのまま出します（そのまま `install-skills` に渡すと `skill not found` になります）。GitHub source はネットワークを使わない約束なので確かめません。
- `config show` は採用した設定ファイル、グローバル設定ファイルのパス、`config.cwd`（CWD の `skill-tools.yaml`。`--project-dir` 指定時は `(not read: --project-dir)` を付ける）と `config.project`（実際に重ねるプロジェクトの `skill-tools.yaml` と `found` / `missing`）、source 種別、index path、fb path、解決済みの `self_skill` を出して終了します。`SKILL_TOOLS_FB_DIR` で上書きしているときはそのパスも出します。API key の値は出しません。
  - `source.*` は**スキルカタログの取得元**（local ならリポジトリのパス）で、この CLI 自身の場所ではありません。CLI 自身は `package.pyproject`（`pyproject.toml` の絶対パス）と `package.readme`（`[project].readme` が指すファイル）で出します。wheel など `pyproject.toml` が同梱されないインストールでは `package.pyproject: (not shipped with this install)` と `package.dir`（`skill_tools` パッケージの場所）を出し、`package.readme` は出さず終了コード `0` で終わります。
  - `source.fingerprint` / `resolved.commit` は、設定中の source と一致する index があるときだけ、index に保存済みの値を出します。source のファイルを読み直して再計算しないため、巨大な local source でも即座に終わります。index が無い・source が一致しないときは fingerprint 行を出しません（`index: missing` / `index.source: mismatch`）。
- `build-index` でAPIキーが必要な場合は、環境変数を設定するか、ソース checkout の `tools/skill-tools/.env.example` を `tools/skill-tools/.env` にコピーして設定します。

### インデックスの鮮度ゲートと埋め込みの再利用

`build-index` は既存インデックスが**7日以内に生成され、設定中の source と一致し、登録スキルの本文hashと埋め込みmetadata hashも一致する**場合、再生成せず `Index is up to date: ...` を出して終了コード `0` で終わります。判定のため毎回カタログと登録済み`SKILL.md`本文を読みますが、鮮度skip時に全sourceファイルのfingerprint計算や埋め込みは行いません。生成時刻は index の `builtAt`（ISO 8601 / UTC）に記録されます。`builtAt` が無い（旧版で作った）・壊れている・未来の時刻である場合は「鮮度不明」として必ず再生成します。

- `--force` — 鮮度に関わらず必ず再生成します（`--max-age-days` は無視されます）
- `--max-age-days N` — 鮮度ゲートの日数を変更します。`0` は常に再生成する意味になります

鮮度ゲートはsource全体のfingerprintではなく、登録スキルごとの`SKILL.md`本文hashを使います。無関係なファイルの変更でindexを作り直さず、本文の変更は7日以内でも検出します。

再生成が走った場合も、埋め込みを全件やり直すことはしません。埋め込み入力は各スキルの `name` と `description` だけで、その SHA256（index の `embeddingHash`）が前回と同じ行は前回のベクトルをそのまま使います。本文だけの変更ではベクトルを再利用します。再利用は「canonical path 一致」→「`embeddingHash` 単独一致」の順に探すため、スキルをフォルダ移動・リネームしただけならベクトルも再利用されます。実行結果の `embedded: N, reused: M` で、実際に何件を埋め込み直したか確認できます。

**本文検索は埋め込みAPIへ送信しません。** `SKILL.md`本文はローカルindex内のlexicalデータにだけ保存し、APIへ送るのは従来どおりname/description（build時）と検索query（search時）です。indexは`index.path`で指定したローカルcacheなので、本文を破棄する場合はそのindexファイルを削除してください。本文が1 MiBを超えるスキルは対象外になり、スキルIDと上限をstderrに警告します。旧schema indexは検索できず、`build-index`で明示的に再構築してください。

`search`はpure-Python BM25によるcasefold済みUnicode語彙検索と既存意味検索をReciprocal Rank Fusion（RRF）で統合します。JSONは既存フィールドに`canonicalId`と一致周辺の短い`snippet`を追加します。text出力も`canonical_id`と`snippet`を含み、語彙一致のない意味検索結果ではsnippetを空にします。全文本文はsearch outputやrun logへ出しません。

`--json` の検索結果は `score` / `canonicalId` / `path` / `name` / `description` / `tool` / `plugin` / `status` / `snippet` を含みます。`path` は local source なら絶対パス、GitHub source なら blob URL です。`canonicalId`はsource repo相対の`SKILL.md` pathで、snippetは最大240文字です。table mode の列順は `score`、`canonical_id`、`path`、`name`、`snippet` です。

## Run logs

Every `skill-tools` invocation appends its arguments and result to `logs/`, resolved relative to the installed `skill_tools` package（この checkout では `tools/skill-tools/logs`）。`SKILL_TOOLS_LOG_DIR` で保存先を、`SKILL_TOOLS_LOG_MAX_BYTES` でローテーション閾値（既定 `1000000` バイト）を、`SKILL_TOOLS_LOG_DISABLE=1` で記録の無効化を指定できます。

```text
logs/
  input/0001.log    # 実行された CWD と引数
  output/0001.log   # stdout / stderr と終了コード
  .state.json
```

- 入力と出力は別ファイルに分かれ、同じ連番（`0001.log` 同士）と各アイテムの `run` マーカーで紐づきます。通常は `logs/input/` だけを眺めれば十分で、対応する出力が必要なときだけ同じ番号の `logs/output/` を開きます。
- `search`結果のstdoutはライブ表示しますが、本文snippetを保存しないようrun logでは`[search output redacted]`に置き換えます。
- `--fb` も実行ログの対象です。`--fb-text` の値は input ログでは `[fb text redacted]` に置き換えます。標準入力で渡した本文は引数に出ません。保存パス（stdout）は通常どおり残します。本文の正本は FB ファイルです。
- ローテーションはサイズのみで判定し、アイテム（1 回の実行）の途中では切りません。閾値を超える大きなアイテムは 1 件だけそのまま書き切ります。
- ログの書き込みに失敗してもコマンドの結果や終了コードには影響しません。

## Safety and exit codes

- GitHub source は指定 ref を commit SHA に固定し、truncated tree は拒否します。
- GitHub source はサブモジュール（gitlink）を辿ります。`.gitmodules` の URL（github.com のもの、または `../<repo>.git` の相対指定）から、記録された commit のツリーを取得し、サブモジュールのパスの下のファイルとして扱います。`.gitmodules` が無い・記載が無い・github.com 以外の URL のときは、ファイルを黙って欠落させずエラーで止まります。リポジトリ数だけ API 呼び出しが増えるので、レート制限に当たるときは環境変数 `GITHUB_TOKEN` を設定します（設定すれば `Authorization` ヘッダーで送ります）。
- symlink の検査・走査の除外は Windows の Junction にも同じく効きます（`Path.is_symlink()` は Junction で False のため、`skill_tools/fs_links.py` の `is_link_like` で判定）。local source で git が Junction 越しに列挙したファイルは数えません。
- local source は Git 管理対象または `.gitignore` 対象外のファイルだけを束ね、さらにバンドルコピーの除外/包含ポリシー（既定除外 → `.gitignore` → `.skill-tools` の `include:`）で絞り込みます。
- 配置は staging 完了後に置換し、後続失敗時は完了済みの置換を rollback します。
- managed install/update/removeはproject単位lockと`.skill-tools/transaction.json` journalで複数directoryとmanifestの変更を追跡し、次回のmanaged操作時に中断journalを検出してrollbackまたは安全に停止します。通常のprocess terminationで復旧できるよう設計していますが、複数directoryとmanifestを単一OS atomic operationとはみなさず、電断・ストレージ障害時の完全な原子性は保証しません。
- フック操作も同じlockとjournalに乗ります。フックは他のファイルと共有するdirectory（`.claude/hooks/` の `logs/` `state/` 等）や登録JSONを扱うため、directory単位ではなく**ファイル単位**でバックアップ（状態ディレクトリの `backups/`。プロジェクトでは `.skill-tools/backups/`、`--global` ではグローバルの状態ディレクトリ）→ 適用を記録し（journal schema v3。バックアップのパスを状態ディレクトリ相対で書く。v2 の journal も復旧できます）、中断時はバックアップから戻します。登録ファイル・manifestは一時ファイル→renameで置換するので、エージェントが途中状態を読むことはありません。
- manifestは schema v3（スキルの `entries` とフックの `hooks` の2配列。スキルの entry は方式 `mode` を持ち、リンクの entry はストア相対の位置 `store` を持ってファイルの hash は持ちません）です。v1・v2 のmanifestはそのまま読め、次の書き込みでv3になります。古いskill-toolsはv3 manifest・新しい版の journal（リンクの操作は journal schema v4）を「unsupported」として変更を拒否するので、0.7.0 より前の skill-tools で一度でも書いたプロジェクトを扱う場合は、skill-toolsを更新してください。
- リンクの entry の drift 検査: 配置先がリンクでない（ふつうのディレクトリに置き換わっている）、または記録したストアの entry 以外を指しているときは、`--force` を付けても `update-skills` / `remove-skills` は止まります（リンクの代わりに置かれた利用者のディレクトリを消さないため）。リンク先のストアの entry が消えているときは、`--force` を付けた `update-skills` が作り直し、`remove-skills --force` はリンクを消します。ストアの中身の drift は、ストアの manifest の hash で検査します。
- リンクを消す・置き換える・中断から戻すときは、リンクそのものだけを扱い、リンク先（ストア）の中身は消しません。プロジェクトのルートやスキルの配置先がストアの中に解決されるとき（リンクの中を CWD にした、など）は、`install-skills` / `update-skills` / `hooks install|update` は終了コード `2` で止まります。
- manifestのlocal source pathはproject内にある場合だけ相対化し、外部sourceは絶対pathとして残ります。machine-localな情報になり得るため、manifestを共有・公開する前に内容を確認してください。secretは記録しません。
- `install-tools` は `repo-tools.yaml` の `install` 文字列を source ルートでそのまま実行します（`uv tool install` / `pnpm add -g` 等）。信頼できる source のこのファイルだけを対象にし、GitHub source では実行しません。
- プロジェクトのルートがホーム、またはホームの祖先のとき（ホームで実行した、または `--project-dir ~` を付けた）、`install-skills` / `update-skills` / `hooks install` / `hooks update` は終了コード `2` で止まり `--global` を案内します（0.6.0 からの挙動の変更です。以前はホームの `.claude/skills` と `.skill-tools/` に入っていました）。同じファイルを、ホームの manifest とグローバルの manifest が別々に管理する状態を防ぐためです。すでにホームで入れたスキルは、ホームで `skill-tools installed-skills` で確認して `skill-tools remove-skills` で片付けてから、`skill-tools install-skills --global <skill>...` で入れ直します（`installed-skills` / `remove-skills` はホームでも動きます）。フックも同じく `hooks installed` / `hooks remove` で片付けてから `hooks install --global` で入れ直します。
- source・index・destination をコード位置や CWD から暗黙推測しません。

終了コードは `0`（成功）、`2`（catalog / configuration / index、および `--fb` の名前不一致・曖昧・使用法エラー）、`3`（source）、`4`（install: skill・フックの配置と drift・tool install コマンド）、`1`（API key、`--fb` の空本文、FB ファイルの書き込み失敗などその他）です。

## Development

```powershell
uv sync
uv run pytest tools/skill-tools/tests
uv run ruff check tools/skill-tools
uv tool install --editable tools/skill-tools --force
skill-tools --help
```
