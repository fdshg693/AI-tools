# agents-rules

リポジトリ各所の `AGENTS.md` を、AIコーディングツールごとのディレクトリスコープ付きルールファイルへ変換する CLI。

| `--target`    | 出力先（既定）                               | スコープ指定                                    |
| ------------- | -------------------------------------------- | ----------------------------------------------- |
| `cline`       | `.clinerules/<dir>.md`                       | `paths:`                                        |
| `copilot`     | `.github/instructions/<dir>.instructions.md` | `applyTo:`                                      |
| `antigravity` | `.agents/rules/<dir>.md`                     | `trigger: glob` / ルートは `trigger: always_on` |
| `cursor`      | `.cursor/rules/<dir>.mdc`                    | `globs:`                                        |

`<dir>` は `AGENTS.md` のあるディレクトリをリポジトリルート相対で `-` 連結したもの（例: `tools/aim/AGENTS.md` → `tools-aim`）。ルートの `AGENTS.md` は `root` になり、全ファイルに適用される。本文は `AGENTS.md` をそのままコピーする。

このリポジトリでは以前 lefthook の pre-commit で毎回自動生成していた。しかし普段は `AGENTS.md` / `CLAUDE.md` だけで足り、`AGENTS.md` を1つ触るたびに生成物の大量差分が出ていたため、手動実行の CLI に切り出した。Cline / Copilot / Antigravity 向けのルールが必要なときにだけ実行する。

## インストール

```powershell
uv tool install --editable tools/agents-rules
```

`docs/integrations/justfile` からも入れられる。

```powershell
just -f docs/integrations/justfile agents-rules-local
just -f docs/integrations/justfile agents-rules-git
```

インストールせずにリポジトリ内で使うなら `uv run agents-rules ...` でよい（uv workspace のメンバー）。

## 使い方

```powershell
agents-rules --version
agents-rules                          # cline + copilot + antigravity を生成（= --target all）
agents-rules -t cline                 # Cline だけ
agents-rules -t copilot -t antigravity
agents-rules -t cursor                # Cursor は all に含まれない。明示したときだけ生成
agents-rules --dry-run                # 書き込まず new / changed / unchanged を表示
agents-rules --check                  # 生成物が古ければ終了コード1（CI 向け）
agents-rules --list-sources           # 対象になる AGENTS.md の一覧
agents-rules -x ".kilo/*" -x temp     # 走査から除外（ルート相対の glob、複数可）
agents-rules -t cline --output-dir out/cline
agents-rules --repo-root C:\src\project
```

| オプション        | 意味                                                                                          |
| ----------------- | --------------------------------------------------------------------------------------------- |
| `-t`, `--target`  | `cline` / `copilot` / `antigravity` / `cursor` / `all`。複数指定可。既定 `all`（cursor 除く） |
| `--repo-root`     | 走査するルート。既定は cwd から親へ `.git`、無ければ `ai-tools.yaml` のあるディレクトリ       |
| `--output-dir`    | 出力先を上書き。`--target` を1つだけ指定したときのみ                                          |
| `-x`, `--exclude` | 走査から除外するディレクトリの glob（ルート相対）                                             |
| `-n`, `--dry-run` | 書き込まずに予定を表示                                                                        |
| `--check`         | 書き込まず、古い生成物があれば終了コード1                                                     |
| `--list-sources`  | 対象 `AGENTS.md` の一覧だけを表示                                                             |
| `-q`, `--quiet`   | ファイルごとの行を省き、ターゲットごとの集計だけ出す                                          |

- `.git` / `node_modules` / `.venv` / `__pycache__` は常に走査しない。
- 内容が変わらないファイルは書き換えない。
- `AGENTS.md` を削除しても、対応する生成物は消さない。不要になった生成物は手で消す。

### 出力先の決め方

1. `--output-dir`
2. リポジトリルートの `ai-tools.yaml` にある `tools.<tool>.rules_from_agents_md.output_dir`（Copilot は `instructions_from_agents_md`）
3. 上表の既定

`ai-tools.yaml` が無いリポジトリでも既定位置で動く。

## ファイル構成

- `agents_rules/cli.py` — 引数解析とモード（生成 / `--dry-run` / `--check` / `--list-sources`）
- `agents_rules/generate.py` — リポジトリルート探索、`AGENTS.md` 走査、`ai-tools.yaml` 読み込み、書き込み
- `agents_rules/targets.py` — ターゲットごとの出力名とフロントマター
- `tests/` — `uv run pytest tools/agents-rules/tests`
