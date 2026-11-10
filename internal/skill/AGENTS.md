# skill/ — SKILL.md本体（meta:ブロック）を扱うスクリプト

- マーケットプレイス登録の有無に関わらず、リポジトリ全体の`SKILL.md`を対象にする（`plugin_meta/`とは異なり`ai-tools.yaml`の登録有無を見ない）
- `set/` — フィールドを補完・変更する（`set_skill_versions.py`, `set_skill_descriptions.py`, `bump_skill_versions.py`, `skill_meta_field_fill.py`）
- `check/` — lefthook等から呼ばれる検査専用スクリプト（`check_skill_version_bump.py`, `check_skill_repo_tools.py`, `check_repo_tool_relations.py`）。ファイルを書き換えない
- `query/` — 関係グラフなど、書き換えない列挙・照会（`list_skill_tool_impact.py`）。lefthookには繋がない
- `util/` — 上記が共有するヘルパー（frontmatterの読み書き、`meta_field.yaml`ローダ、`repo-tools.yaml`ローダ（`repo_tools_registry.py`）、workspace 依存読み取り（`workspace_deps.py`）、スキル↔ツールグラフ（`skill_tool_graph.py`）等）。`set/`・`check/`・`query/`以外から新規に依存を追加しない
- 実行は`tools/internal`をcwdとして`python -m skill.<set|check|query>.<module>`（`justfile`のレシピ、または`uv run --directory tools/internal python -m ...`経由）
