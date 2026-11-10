# model-list — OpenRouterモデル一覧ツール

**関連スキル: `claude-plugins/topics/skills/openrouter-docs/SKILL.md`**

OpenRouterの[Models API](https://openrouter.ai/api/v1/models)からモデルを取得して標準出力に表で出す。既定は直近1週間の処理トークン数が多い順（`sort=most-popular`）。`--id` 指定時は ID の部分一致で絞り、OpenRouter への追加が新しい順（`sort=newest`）で出す。`--pareto` は価格と `coding_index` の Pareto 最適モデルを表で出す（bucket 分けはしない）。インタラクティブな HTML レポートは[model-select](../model-select/)の責務。

## セットアップ

認証不要。APIキー等の事前設定は無い。

## インストール

グローバルCLIとして使う場合は `uv tool install --editable`（`pip install -e` の代替）でエディタブルインストールする。リポジトリルートから実行可能。

```bash
uv tool install --editable tools/openrouter/model-list
```

インストール後は `model-list` コマンドが PATH 上でどこからでも使える。

## 使い方

```bash
model-list
```

デフォルトは人気上位 100 件を表（`id` / `name` / `context_length`）で出す。

```bash
model-list --provider openai
model-list --limit 20
model-list --id gpt-5
model-list --id openai/gpt --limit 10
model-list --json
model-list --list-providers
```

- `--provider` は作成組織 slug（`--list-providers` の値）。API の `model_authors` にそのまま渡す。未知の値は空表で終了コード 0。
- `--id` はモデル ID の部分一致（大文字小文字は区別しない。名前は見ない）。カタログ全件から探し、新しい順に `--limit` 件出す。ヒットなしは空表で終了コード 0。
- `--limit` は 1〜1000。既定の人気順一覧では API の `limit` にそのまま渡す。`--id` 指定時は絞り込み後の表示件数。`--pareto` では使わない。
- `--list-providers` はモデル一覧の代わりに、カタログ上の作成組織 slug をユニーク化して出す。
- `--json` は同じ内容を JSON で出す。

ライブ取得の動作確認は、インストール後に上記コマンドを手動で実行する（ユニットテストは HTTP を呼ばない）。

## Pareto 比較

```bash
model-list --pareto
model-list --pareto --provider openai
model-list --pareto --provider openai,anthropic,google
model-list --pareto --min-index 65
model-list --pareto --min-index 20
model-list --pareto --price completion
model-list --pareto --json
model-list --rebuild
model-list --pareto --rebuild
```

初回の `--pareto`、または `--rebuild` で OpenRouter から取得し、`tools/openrouter/model-list/output/pareto.json` に保存する。以降の `--pareto` はキャッシュを再利用する（プロバイダ絞り込みや `--min-index` の変更では再取得しない）。データが古くなったら `--rebuild`。`--rebuild` だけのときは書き出したキャッシュの絶対パスを標準出力に出す。

- 対象プロバイダの既定は [model-select](../model-select/) と同じ 9 系統（`openai` / `anthropic` / `google` / `qwen` / `z-ai` / `minimax` / `x-ai` / `moonshotai` / `deepseek`）。`--provider` でカンマ区切りの subset に狭める。ここでの未知の slug はエラー。
- `id` に `:` を含む variant（`:free` / `:batch` / `:thinking` 等）と、`coding_index` を持たないモデルは除外する。
- キャッシュは `coding_index` 20 以上を保持する。表示時の足切りは既定 50、`--min-index` で上下できる（最小 20）。20 まで下げる再取得は不要。
- bucket（階層）分けはしない。絞り込み後の全モデルを 1 つの集合として Pareto 最適にする。
- 価格は model-select と同じく、`pricing` のベース値と `pricing.overrides[]` の最大値（$/M tokens）。比較軸の既定は `prompt`（入力）。`--price completion` で出力軸。
- 出力は `id` / `name` / `index` / `price`。`price` の昇順（2 軸 Pareto なので `index` も非減少）。

## ファイル構成

```text
tools/openrouter/model-list/
├── README.md              # 本ファイル
├── AGENTS.md / CLAUDE.md  # @./README.md インクルードのみ
├── pyproject.toml          # `model-list` コンソールコマンドのパッケージング
├── .gitignore              # output/*.json を無視（.gitkeepは追跡）
├── model_list/
│   ├── __init__.py
│   ├── fetch.py             # OpenRouter Models API呼び出し（一覧 / Pareto用）
│   ├── format.py            # 表 / JSON 整形
│   ├── pricing.py           # pricingベース値とoverridesの最大値算出
│   ├── pareto.py            # スコープ・Pareto最適・プロバイダ/カットオフ
│   ├── cache.py             # Paretoレコードの保存と再利用
│   └── cli.py               # エントリポイント（main）
├── tests/
│   ├── test_cli.py
│   ├── test_fetch.py
│   ├── test_format.py
│   ├── test_pricing.py
│   ├── test_pareto.py
│   └── test_cache.py
└── output/
    └── pareto.json          # --rebuild / 初回 --pareto で生成（gitignore対象）
```
