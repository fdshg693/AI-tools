# aim — シンプルなモデル呼び出しCLIツール

- **関連スキル**:
  - `claude-plugins\my-tools\skills\aim-cli\SKILL.md`
  - `claude-plugins\my-tools\skills\aim-lib`
  - `claude-plugins\topics\skills\openrouter-docs\SKILL.md`
- **関連ツール**:
  - `tools/aim-use/`: この aim CLI を前提としたツール群

CLIのフラグや`@path`/`--parallel`の挙動を変えたら、同じ変更で`aim --ai-help`と`aim-cli`スキルの判断節を見る。フラグ表はスキルに戻さない。

- エージェント機能は扱わず、AIモデルの単発呼び出しに集中したCLIツール
- 複数プロバイダに対応するため [OpenRouter](https://openrouter.ai/) の Python SDK（`openrouter`）を使う

## インストール

グローバルCLIとして使う場合は `uv tool install --editable`（`pip install -e` の代替）でエディタブルインストールする。リポジトリルートから実行可能。

```bash
uv tool install --editable tools/aim
# 既存インストールを更新する場合
uv tool install --reinstall --editable tools/aim
```

インストール後は `aim` コマンドが PATH 上でどこからでも使える。

## セットアップ（APIキー）

以下のいずれかで `OPENROUTER_API_KEY` を指定する（環境変数が優先）。

1. 環境変数 `OPENROUTER_API_KEY`
2. `tools/aim/.env`（`.env.example` をコピーして値を設定。`aim` 実行時のカレントディレクトリに依存せず、常にこのファイルを参照する）

```bash
cp tools/aim/.env.example tools/aim/.env
# .env を編集して OPENROUTER_API_KEY=sk-or-... を設定
```

## 使い方

```bash
# 引数でプロンプトを渡す（--model 省略時は models.json の default）
aim --prompt "フランスの首都は？"

# 標準入力からプロンプトを渡す（--prompt 省略時は stdin を読む）
echo "フランスの首都は？" | aim --model gpt-120b
cat prompt.txt | aim --model gpt-luna

# プロンプト中の @path をファイル内容に展開して1回呼び出す
aim --prompt "@src/foo.py を要約して"
aim --prompt "@a.py と @b.py の差分を説明して"

# 複数プロンプトを並列に呼び出す（各 --prompt が1ジョブ。@ はファイル取り込み）
aim --parallel --prompt "@a.py 要約して" "@b.py 要約して"
aim --parallel --prompt "質問A" "質問B"
aim --parallel --format json --prompt "@a.py 要約して" --prompt "@b.py 要約して"

# 人間向けの使い方
aim --help

# エージェント向けの使い方（モデル説明つき）
aim --ai-help

# 利用可能なモデル一覧を表示
aim --list-models

# 入力・出力単価（$/M tokens、最悪ケース）を表示。APIキー不要
aim --cost
aim --cost --model gpt-luna
aim --cost --format json --model glm-5.2

# Web Search/Web Fetch（OpenRouter Server Tools）を有効にして呼び出す
aim --web --prompt "2026年8月時点の最新ニュースは？"
```

### オプション

| オプション             | 必須 | 説明                                                                                                                                                        |
| ---------------------- | ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--model`              | -    | 利用するモデルの略記（`models.json` のキー。省略時は `default`。`--list-models` で一覧表示）                                                                |
| `--prompt`             | △    | プロンプト文字列。複数指定は `--parallel` が必要。省略時は標準入力から1件読む                                                                               |
| `--help`               | -    | 人間向けの使い方を表示して終了する                                                                                                                          |
| `--ai-help`            | -    | エージェント向けに使い方・モデル一覧・各モデルの説明を表示して終了する                                                                                      |
| `--list-models`        | -    | 利用可能なモデルの一覧（略記と実際のモデルID）を表示して終了する                                                                                            |
| `--cost`               | -    | 指定した `--model`（省略時はデフォルト）の入力・出力単価（$/M tokens）を表示して終了する。APIキー不要                                                       |
| `--web`                | -    | Web Search/Web Fetch（OpenRouter Server Tools）を有効にする（モデルが必要と判断した場合のみ呼ばれる）                                                       |
| `--parallel`           | -    | 複数の `--prompt` を並列呼び出しする。各プロンプトは独立（`@path` はジョブの区切りではない）                                                                |
| `--jobs`               | -    | 並列実行数（1〜10、省略時4）。`--parallel` 専用                                                                                                             |
| `--format`             | -    | `markdown` / `json`。未指定かつ `--parallel` なしは応答本文のみ。`--parallel` 時の未指定は markdown。`json` は単発でも1要素の配列。`--cost` 時は単価の JSON |
| `--full-content-names` | -    | ディレクトリ `@path` で内容を含めるファイル名のカンマ区切り。省略時は配下の全ファイル。`--parallel` の有無を問わず効く                                      |

### 利用可能なモデル

`--model` に指定できる略記・デフォルト・各モデルの説明は `tools/aim/models.json` がSSOT。範囲外の略記はエラーになる。

```json
{
  "default": "mini-m3",
  "models": {
    "gpt-120b": {
      "enable": true,
      "id": "openai/gpt-oss-120b:free",
      "description": "非常に簡単で精度が求められないタスク向け。無料枠。"
    },
    "mini-m3": {
      "enable": true,
      "id": "minimax/minimax-m3",
      "description": "標準の選択。特に理由がなければこれを使う。"
    }
  }
}
```

- 追加・改名・有効/無効・デフォルト変更・説明の更新は `models.json` を編集するだけ。コードや README の表は触らない
- `enable` は必須の真偽値。`true` のモデルだけが `--model` / `--list-models` / `--ai-help` とライブラリの `MODELS` に出る。定義は残したまま外すときは削除せず `false` にする
- `default` は `enable: true` の略記でなければならない
- 人間向けの確認は `aim --help` と `aim --list-models`（略記と実際のモデルID）
- エージェント向けの確認は `aim --ai-help`（使い方に加えて各モデルの `description` を出す）
- 略記は元のモデルIDが推測できる形にする
- system プロンプトやマルチターンなど、エージェント的な機能は扱わない（単発の user メッセージ 1件のみ。`--parallel` 時もジョブごとに user メッセージ 1件）
- `--format` 未指定かつ `--parallel` なしのとき、標準出力にはモデルの応答テキストのみを出力する（パイプで後続処理しやすい）

### 入力・出力単価（`--cost`）

`aim --cost` はチャット呼び出しをせず、OpenRouter の [Models API](https://openrouter.ai/api/v1/models)（`GET /api/v1/model/{author}/{slug}`）から指定モデルの `pricing` を取得して終了する。認証不要（APIキーは見ない）。`--prompt` は不要。

- 表示単位は `$/M tokens`（入力=`prompt`、出力=`completion`）。`--format json` なら `prompt_per_million` / `completion_per_million`
- ライブラリからは `get_model_cost` で単価を取り、入力テキストの概算コストは `estimate_prompt_tokens`（1 token ≈ 4 chars）と `prompt_cost_usd`（入力のみ。出力は含めない）で出す。複数プロンプトは単価取得を1回にして足す。単発なら `estimate_prompt_cost_usd(model, text)`
- 価格が複数ある場合（`pricing` のベース値と `pricing.overrides[]` のコンテキスト長閾値などによる割増）は、[model-select](../openrouter/model-select/) と同じく**最大値**を採用する（安全側=最悪ケース。閾値条件は判定しない）。プロバイダ別の `/endpoints` 価格差は見ない
- モデルIDの `:free` variant（例: `openai/gpt-oss-120b:free`）はカタログに無いことがあり、呼び出し単価は `0` として扱う（HTTP は叩かない）
- その他の variant は完全一致で取得し、404 なら suffix を除いたベース ID を再試行する

### `@path` によるファイル取り込み

`--prompt` および標準入力の本文から、トークン先頭（行頭または空白の直後）の `@path` を検出する。相対パスは実行時のカレントディレクトリ基準。空白を含むパスは `@"path with spaces"` または `@'path'`。

`--parallel` とは独立した機能で、ジョブの区切りには使わない。各プロンプト内の `@path` をその位置の本文ブロックへ置換する。

- `--parallel` なし: `--prompt` は1件。全 `@path` を展開して API は **1回**
- `--parallel` あり: `--prompt` を複数渡すと各プロンプトが1ジョブ。`@` の有無は問わない。1プロンプトに `@path` が複数あっても1ジョブ（両方をそのプロンプトへ展開する）
- `@src/foo.pyを要約して` のように助詞が直結していても、実在するパスの最長一致で切る
- `foo@gmail.com` や、実在しない `@user` のような言及は本文に残す。一方 `src/missing.py` のように `/` `\` を含む・`./` `../` `~/` ・ドライブレターで始まる明示パスが実在しない場合はエラー
- glob（`@src/*.py`）は対象外。パスを列挙する
- CWD に同名ファイルがあると `@property` のような語も展開され得る
- 単発経路でパス読込失敗・欠落は非ゼロ終了。`--parallel` は失敗したプロンプトだけ `success: false` にし、プロセスの終了コードは0（モデル略記や `--jobs` 範囲外だけ非ゼロ）

`--parallel` でプロンプトが1件かつその中に `@path` が2件以上ある場合は、旧来の「`@` でジョブ分割」と取り違えやすいので stderr に注意を出す（処理自体は1ジョブとして続行する）。

### Web Search / Web Fetch（`--web`）

`--web`を付けると、OpenRouterのServer Tools（`openrouter:web_search`・`openrouter:web_fetch`）がそのリクエストで使えるようになる。あくまでモデルに「使える状態」を渡すだけで、実際に呼ぶかどうか（0回か複数回か）はモデル自身の判断。Server Toolsの実行はOpenRouter側でリクエスト/レスポンス1往復の中に収まるため、この CLI の「プロンプト1件→応答テキスト1件」という単発設計は変わらない。

- 付けない場合は従来通り（ツール定義は送らない）
- 付けた場合、ツール定義がリクエストに追加される分、使わなかったとしてもprompt tokens・costがわずかに増える
- モデルによっては関連するプロンプトでも検索を呼ばないことがある（`mini-m3`で検証時、最新情報が必要なプロンプトでも`--web`だけでは検索が呼ばれないケースを確認済み）。使わせたい場合はプロンプト内で明示的にWeb検索の利用を指示すると成功率が上がる
- ログ（`calls.jsonl`）にツール使用有無を記録するフィールドは無い。Server Tools分のコストは既存の`cost`フィールド（`usage`由来）に含まれる

## ログ

呼び出しごとに `tools/aim/logs/<trace.tool>/<YYYY-MM-DD>.jsonl`（JSON Lines）へ1行追記される。CLIのソースディレクトリ基準の絶対パスを使うため、実行時のカレントディレクトリには依存しない。

- 1ファイルに書き続けると際限なく肥大化するため、`trace.tool`（例: `aim-cli`/`aim-summarize`）でフォルダ分けした上で、`timestamp`の日付（呼び出し元のローカル日付）でファイルを分割する
- `trace`自体が無い、または`trace.tool`が空の場合は`unknown`フォルダにまとめる（`aim`直接利用時は常に`trace: {"tool": "aim-cli"}`が付くため、`unknown`は主にライブラリ利用時にtraceを渡し忘れた場合に発生する）

```json
{
  "timestamp": "2026-07-09T22:22:34+09:00",
  "model": "minimax/minimax-m3",
  "prompt": "フランスの首都は？",
  "cost": 8.85e-6,
  "prompt_tokens": 15,
  "completion_tokens": 11,
  "total_tokens": 26,
  "generation_id": "gen-1783603352-zXMyzMZpyjJ88CJF5wwD",
  "user": null,
  "session_id": null,
  "trace": { "tool": "aim-cli", "trace_id": "3f2a9c1e4b7d4f0aa1e3c6d9b8f7a2c5" }
}
```

- `cost` / `*_tokens` / `generation_id` は OpenRouter レスポンスの `usage` / `id` フィールドからそのまま転記（追加のAPI呼び出しは発生しない）
- 応答本文（completion）はログに含めない
- `logs/`配下のログファイルはプロンプト本文を含み得るため Git管理対象外（`.gitignore` 参照）。ディレクトリ自体は `.gitkeep` で追跡
- `call()`/`call_async()` は呼び出し元が `user`/`session_id`/`trace` を渡せる（いずれも省略時は `None`）。`trace` はOpenRouterのSDKの `trace`（`trace_id`/`trace_name`/`span_name`/`generation_name`/`parent_span_id`の既知キー + 任意の追加キーを持つdict）にそのまま渡され、Grafana Cloudへのブロードキャスト設定時にはトレースのカスタム属性としても反映される（詳細は`claude-plugins/topics/skills/openrouter-docs`スキルの`references/observability.md`参照）
- `aim` コマンドを直接実行した場合は常に `trace: {"tool": "aim-cli"}` が記録される。`--parallel` の各ジョブには同じ `tool` に加えて `prompt_index`（1始まり）を付与する。そのプロンプトに `@path` があれば先頭のものを `file_path`（`@` を付けない解決前のパス）にも付ける
- `trace.trace_id`（32桁hex、OTel準拠のtrace id）は呼び出し元が指定しない限り `call()`/`call_async()` が自動生成し、OpenRouterへの送信・ログ記録の両方に使う。これがGrafana Cloud連携時のTrace IDそのものになるため、ログの`trace.trace_id`をそのままGrafana CloudのTempoで検索すれば対応するトレースにたどり着ける（詳細は下記「Grafana Cloudへのログ配信」参照）
- `call()`/`call_async()` に `return_trace_id=True` を渡すと、戻り値が `(応答テキスト, trace_id)` のタプルになる（省略時は従来通り応答テキストのみ）。呼び出し元が自身の処理単位（例: 対象ファイルパスやDBレコード）とtrace_idを紐づけて保存したい場合に使う

## Grafana Cloudへのログ配信（任意）

OpenRouterのBroadcast機能を使うと、`aim`経由の呼び出し（および`aim-summarize`経由の呼び出し）をGrafana Cloud（OTLP/Tempoトレース）にも並行して送信できる。ローカルの`logs/calls.jsonl`は今まで通り残るため、これは二重化であり置き換えではない。

- 設定はOpenRouterダッシュボード（[`https://openrouter.ai/settings/observability`](https://openrouter.ai/settings/observability)）での手動設定のみ。このCLI/リポジトリ側に自動設定コードは持たない（Broadcast設定にはManagement API Keyという別種の強い権限を持つキーが必要になるため）
- 設定手順・カスタムメタデータのマッピング（`user`→`user.id`、`session_id`→`session.id`、`trace`の各キー→`trace.metadata.*`等）・TraceQLクエリ例の詳細は `claude-plugins/topics/skills/openrouter-docs` スキルの `references/observability.md` を参照
- **ローカルログとGrafana側トレースの突き合わせ**: OpenRouterのレスポンスにはGrafana Cloud側のtrace_id/span_idは含まれない（APIが返さない）。そのため `aim` 側で毎回trace_idを自前生成し、OpenRouterへの送信とローカルログの両方に使うことで、ローカルログの`trace.trace_id`＝Grafana CloudのTrace IDという対応を保証している。span_id自体はAPI経由で取得・指定する手段が無いが、1リクエスト＝1トレース（実質1スパン）のため、trace_idでトレースを開けば中のスパンも自動的に見え、実務上span_idの保存は不要

## エラー時の挙動

APIキー未設定・モデルID誤り・OpenRouter側エラー（401/402/429など）が発生した場合、エラーメッセージを標準エラー出力に表示し、非ゼロで終了する。

## ファイル構成

```
tools/aim/
├── README.md       # 本ファイル
├── PLAN.md          # 実装プラン
├── pyproject.toml    # パッケージ定義 + console script (aim)
├── aim_cli.py         # CLI本体（call / call_async のライブラリ面）
├── aim_at.py          # プロンプト中の @path 検出・解決
├── aim_files.py       # ファイル/ディレクトリ本文の組み立て
├── aim_parallel.py    # --parallel 時のファンアウトと結果整形
├── aim_pricing.py     # --cost: Models API から最悪ケースの入出力単価。入力トークンからのUSD概算
├── models.json        # デフォルト略記 + 略記 → {enable, id, description}（SSOT）
├── .env.example
├── .env               # gitignore対象
├── .gitignore
└── logs/
    ├── .gitkeep
    └── <trace.tool>/          # 例: aim-cli/, aim-summarize/, unknown/ （gitignore対象）
        └── <YYYY-MM-DD>.jsonl
```
