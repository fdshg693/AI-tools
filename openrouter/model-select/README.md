# model-select — OpenRouterモデル選定ツール

**関連スキル: `claude-plugins/topics/skills/openrouter-docs/SKILL.md`（特に[references/models-pricing-benchmarks.md](../../../claude-plugins/topics/skills/openrouter-docs/references/models-pricing-benchmarks.md)）**

OpenRouterの[Models API](https://openrouter.ai/api/v1/models)から取得したArtificial Analysisベンチマーク（`coding_index`）と価格を判断材料に、OpenAI/Anthropic/Google/Qwen/Z.ai/MiniMax/xAI/Moonshot AI/DeepSeek系列モデルの選択を行いやすくするCLIツール。実行するたびにOpenRouter APIをライブ取得し（キャッシュ無し）、結果を自己完結HTML（サーバー・外部JS/CSS取得不要）として出力する。ランク分けの閾値・bucketステップ幅・プロバイダ絞り込み・表示モード（フル/Pareto）はHTML上でインタラクティブに変更できる。

## セットアップ

認証不要。APIキー等の事前設定は無い。

## インストール

グローバルCLIとして使う場合は `uv tool install --editable`（`pip install -e` の代替）でエディタブルインストールする。リポジトリルートから実行可能。

```bash
uv tool install --editable tools/openrouter/model-select
```

インストール後は `model-select` コマンドが PATH 上でどこからでも使える。

## 使い方

```bash
model-select
```

実行すると `tools/openrouter/model-select/output/report.html` に結果を書き出し（実行のたびに上書き）、書き出した絶対パスを標準出力に表示する。生成された `report.html` をブラウザで開いて見る。レポートには実行時刻（ローカルタイムゾーン付き ISO 8601）を `<meta name="generated-at">` とフッタの `<time>` 要素の両方に埋め込むので、いつのスナップショットかを確認できる。

## 判定ロジック

Python側（生データ取得）とHTML側（埋め込みJSでの動的計算）で責務が分かれている。

**Python側（`model-select`実行時に確定する部分）**

1. **スコープ**: `id`が`openai/`・`anthropic/`・`google/`・`qwen/`・`z-ai/`・`minimax/`・`x-ai/`・`moonshotai/`・`deepseek/`のいずれかで始まるモデルのみ（`model_authors`クエリで絞り込み）。`id`に`:`を含むvariant（`:free`/`:batch`/`:thinking`等）と、`benchmarks.artificial_analysis.coding_index`を持たないモデルは除外する。
2. **足切り**: `coding_index`が50未満のモデルは、OpenRouter APIへの`min_coding_index`クエリ（転送量削減）と`scope.py`側のフィルタ（安全網）の二重で除外する。この50という下限はHTML側の閾値入力でも下回れない。
3. **価格**: 「入力重視（`prompt`価格）」「出力重視（`completion`価格）」の2軸それぞれについて、`pricing`のベース値と`pricing.overrides[]`（コンテキスト長閾値等による割増価格）の中の最大値を採用する（安全側=最悪ケースでの比較）。マルチプロバイダ間の価格差（`/endpoints` API）は考慮しない。

**HTML側（埋め込みJSがブラウザ上で動的に再計算する部分）**

4. **プロバイダ絞り込み**: チェックボックスで作成組織（`id`の`/`前。初期状態は全選択）をオンオフでき、変更のたびに対象モデルを絞り込んでからランク分け・表示をやり直す。選択状態は`localStorage`に保持する。
5. **ランク分け**: `coding_index`の下限（閾値、初期値65・最小50）とbucketステップ幅（初期値3）を数値入力で変更でき、変更のたびに半開区間（`[閾値, 閾値+step)`, ...）でbucket分けし直す。
6. **表示モード**: 「Pareto表示」（初期値）と「フル表示」をラジオで切り替えられる。Pareto表示では同じbucket内で「価格・ベンチマーク双方において自分以上に優れる他モデル」が存在するモデルを除外し、frontier上のモデルだけを残す。フル表示ではbucket内の全モデルを出す。入力重視・出力重視それぞれ独立に判定する。選択状態は`localStorage`に保持する。

モデルが0件のbucketは見出しごと省略する。各セクション冒頭に、プロバイダ絞り込み後の対象モデル総数（ランク分け前）とスコープ全体の件数を表示するので、最終的な表示件数が少ない理由はそこで確認できる。

## 既知の制約

- キャッシュを持たず毎回ライブ取得するため、レート制限に頻繁に触れる場合はAPIキー対応を追加検討する。
- 生成HTMLは外部CDNからのJS/CSS読み込みを行わない完全インライン構成（サーバー・外部JS/CSS取得不要の自己完結）。
- `coding_index < 50`のモデルはPython側取得段階で恒久的に除外されており、HTML側の閾値入力を下げても復活しない。
- プロバイダ絞り込みの再計算・ランク分け・表示モード（フル/Pareto）はHTML埋め込みJSが担う。レコードの`provider`抽出とフィルタUIの埋め込みはPython側テストがあるが、チェック操作後の再描画は`model-select`実行後にブラウザで`output/report.html`を開き、閾値・ステップ・プロバイダチェック・表示モードを変えて手動確認する。

## ファイル構成

```text
tools/openrouter/model-select/
├── README.md              # 本ファイル
├── AGENTS.md / CLAUDE.md  # @./README.md インクルードのみ
├── pyproject.toml          # `model-select` コンソールコマンドのパッケージング（jinja2依存を含む）
├── .gitignore               # output/*.html を無視（.gitkeepは追跡）
├── model_select/
│   ├── __init__.py
│   ├── fetch.py             # OpenRouter Models API呼び出し（model_authors絞り込み・min_coding_index）
│   ├── scope.py              # variant除外 + coding_index必須・下限フィルタ
│   ├── pricing.py             # pricingベース値とoverridesの最大値算出
│   ├── render.py               # Jinja2テンプレートへのレンダリング呼び出し
│   ├── templates/
│   │   ├── report.html.jinja    # ページ骨格。部分テンプレートをJinja includeで組み立て（生成HTMLは自己完結の1ファイル）
│   │   ├── _styles.css          # テーマ・テーブル・フィルタUIのCSS
│   │   ├── _body.html.jinja     # コントロール・セクション・フッタ
│   │   └── js/
│   │       ├── _theme.js        # ライト/ダーク切替
│   │       ├── _providers.js    # プロバイダ絞り込みUIとlocalStorage
│   │       ├── _rank.js         # bucket分け・Pareto最適フィルタ（表示モードで適用切替）
│   │       ├── _boot.js.jinja   # 埋め込みJSONの読み込みと定数
│   │       └── _render.js       # テーブル描画と入力イベント（表示モード含む）
│   └── cli.py                     # エントリポイント（main）
├── tests/
│   ├── test_scope.py
│   ├── test_pricing.py
│   ├── test_cli.py
│   └── test_render.py
└── output/
    └── report.html            # 実行のたびに上書き生成（gitignore対象）
```
