# 内部ツール

- レポジトリ管理等に使われる、便利ツール群
- 同階層の `justfile` から起動できるようにしておく
- lefthookにも紐づけることで、コミット時に自動実行されるようにする

## フォルダ構成（責務ごと）

- `skill/` — `SKILL.md`そのもの（frontmatterの`meta:`ブロック）を扱うスクリプト。マーケットプレイス登録の有無に関わらずリポジトリ全体を走査する
  - `set/` — フィールドを補完・変更する（`set_skill_versions.py`, `set_skill_descriptions.py`, `bump_skill_versions.py`, `skill_meta_field_fill.py`）
  - `check/` — lefthook等から呼ばれる検査のみのスクリプト（`check_skill_version_bump.py`, `check_skill_repo_tools.py`, `check_repo_tool_relations.py`）。env検査はここに混ぜない
  - `query/` — 関係グラフなど、書き換えない列挙・照会（`list_skill_tool_impact.py`）。justレシピのみ。lefthookには繋がない
  - `util/` — 上記が共有するヘルパー（frontmatter読み書き、`meta_field.yaml`ローダ、`repo-tools.yaml`ローダ、workspace 依存読み取り、スキル↔ツールグラフ等）。新規消費者は`set/`・`check/`・`query/`に限る
- `check/` — SKILL.md以外の検査（`check_tool_env_loading.py`：`find_dotenv` / `usecwd=True` / パス無し`load_dotenv()`はjustレシピのみでlefthookに繋がない。`scan_staged_secrets.py`はlefthookのsecretlintジョブから呼ばれ、Windowsのargv長制限を避けるためにgitのステージ済み一覧を分割して渡す）
- `plugin_meta/` — `ai-tools.yaml`（SSOT）を起点に、プラグイン・マーケットプレイス・スキルカタログなどの集約メタ情報を生成するスクリプト
  - `generate/` — `marketplace.json`/`skill-catalog.json`/`CATALOG.md`/Cline rules/Copilot instructions/Cursor rules/READMEセクションなどを再生成する（すべて`generate_*.py`、丸ごと再生成でマージではない）
  - `util/` — `ai-tools.yaml`ローダ（`ai_tools_config.py`）
- `release/` — `repo-tools.yaml`の登録ツールについて、対象フォルダ配下の変更検知に応じて各マニフェスト版数を自動で上げる（Pythonは`pyproject.toml`、Nodeは`package.json`。`bump_tool_versions.py`）。`release: true`は引き続き`.github/workflows/tool-release.yml`のタグ+Release対象だけを表す。`repo-tools.yaml`は`skill/util/repo_tools_registry.py`を経由せず直接読む（同util の新規消費者を`skill/set`・`skill/check`・`skill/query`以外に増やさない方針のため。詳細は[repo-tools-config](../../docs/repo-wide/repo-tools-config.md)参照）
- `precommit/` — lefthookの`pre-commit`から呼ばれる単一エントリ（`python -m precommit fix|check`、justレシピ`precommit-fix`/`precommit-check`）。上記`skill/`・`plugin_meta/`・`release/`の各`main()`をプロセス内で依存順に実行し、タスクごとのglobはステージ済みパスに対してここで判定する。lefthookジョブを1本ずつ増やすとジョブごとに`powershell`+`uv run`の起動コスト（約1秒）がかかるため、新しいPythonタスクは`precommit/__main__.py`の`FIX_TASKS`/`CHECK_TASKS`へ足し、lefthook側は該当ジョブの`glob`に追加するだけにする
- 各スクリプトは`tools/internal`をcwdとして`python -m <package>.<module>`で実行する想定（`justfile`のレシピ、または`uv run --directory tools/internal python -m ...`）。`generate/`配下のスクリプトは`skill/util/`のヘルパーも参照することがある（例: カタログ生成がSKILL.mdのfrontmatterを読む）
- `ai-usage/` — 上記とは独立した自己完結パッケージ（別途`pyproject.toml`を持つ）
