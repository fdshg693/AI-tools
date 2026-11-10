# aim2 — 複数プロバイダ対応 AI モデル呼び出し CLI ツール

- **関連スキル**:
  - `claude-plugins/my-tools/skills/aim2-cli/SKILL.md`
- **設計思想**:
  - エージェント機能は持たせず、AI モデルの呼び出しとローカルログベースの軽量な会話継続に特化
  - 複数プロバイダ（OpenAI, Anthropic, Google Gemini, OpenRouter, Ollama 等）に直接対応
  - Vercel AI SDK をコア基盤に採用し、Dynamic Import（遅延ロード）によって指定されたプロバイダの SDK のみ読み込むことで CLI の高速起動を実現

## インストール

リポジトリルートまたは `tools/aim2` ディレクトリからビルドおよびインストールを行う。

```bash
cd tools/aim2
pnpm install
pnpm build
pnpm add -g .
```

インストール後は `aim2` コマンドが PATH 上でどこからでも使える。

## セットアップ（APIキー・環境変数）

各プロバイダの認証情報は、**プロセス環境変数が最優先**され、未設定の場合は **`tools/aim2/.env`** から固定参照される（リポジトリの `docs/repo-wide/tool-conventions.md` 規約に準拠）。
利用するプロバイダのキーのみ設定されていれば動作する。

1. 環境変数（シェルや CI など）
2. `tools/aim2/.env`（`.env.example` をコピーして設定）

```bash
cp tools/aim2/.env.example tools/aim2/.env
# 利用したいプロバイダのキーを設定
```

主な環境変数:

- `OPENAI_API_KEY`: OpenAI API キー
- `ANTHROPIC_API_KEY`: Anthropic API キー
- `GEMINI_API_KEY` または `GOOGLE_GENERATIVE_AI_API_KEY`: Google Gemini API キー
- `OPENROUTER_API_KEY`: OpenRouter API キー
- `OLLAMA_BASE_URL`: Ollama エンドポイント（省略時: `http://127.0.0.1:11434/v1`）

## モデル設定（models.json）

利用可能なモデル略記（エイリアス）とデフォルトモデルは `tools/aim2/models.json` で管理される。
各モデル定義には `provider` の明示が必須。

```json
{
  "default": "glm-5.3-flash",
  "models": {
    "glm-5.3-flash": {
      "enable": true,
      "provider": "openrouter",
      "id": "z-ai/glm-5.3-flash",
      "description": "OpenRouter 経由の高速・低コストモデル（デフォルト）。"
    },
    "gemini-2.5-flash": {
      "enable": true,
      "provider": "google",
      "id": "gemini-2.5-flash",
      "description": "Google Gemini 2.5 Flash 高速マルチモーダルモデル。"
    },
    "gpt-4o-mini": {
      "enable": true,
      "provider": "openai",
      "id": "gpt-4o-mini",
      "description": "OpenAI の高速・低コストモデル。"
    },
    "claude-3-7-sonnet": {
      "enable": true,
      "provider": "anthropic",
      "id": "claude-3-7-sonnet-20250219",
      "description": "Anthropic Claude 3.7 Sonnet。"
    },
    "llama3.2": {
      "enable": true,
      "provider": "ollama",
      "id": "llama3.2",
      "description": "Ollama ローカル実行モデル。"
    }
  }
}
```

- 追加・改名・有効/無効・デフォルト変更・説明の更新は `models.json` を編集するだけ。コードの変更は不要
- `enable` は必須の真偽値。`true` のモデルだけが `--model` / `--list-models` / `--ai-help` に表示される
- `default` は `enable: true` の略記でなければならない

## 使い方

```bash
# 引数でプロンプトを渡す（--model 省略時は models.json の default）
aim2 --prompt "フランスの首都は？"

# 特定モデルを指定して呼び出す
aim2 --model claude-3-7-sonnet --prompt "Hello"

# 標準入力からプロンプトを渡す
echo "TypeScript の利点は？" | aim2 --model gpt-4o-mini

# 自動発行された session_id は標準エラーに表示される
aim2 --prompt "設計案を3つ出して"

# 同じ session_id を指定してローカル会話履歴を引き継ぐ
aim2 --session-id feature-abc --prompt "前回の続きで2案に絞って"

# プロンプト中の @path をファイル内容に展開
aim2 --prompt "@src/cli.ts を要約して"
aim2 --prompt "@a.py と @b.py の差分を説明して"

# 複数プロンプトを並列に呼び出す（各 --prompt が1ジョブ）
aim2 --parallel --prompt "質問A" "質問B"
aim2 --parallel --prompt "@a.py 要約して" "@b.py 要約して"
aim2 --parallel --format json --prompt "@a.py 要約して" "@b.py 要約して"

# モデル一覧表示
aim2 --list-models

# エージェント向けヘルプ表示（モデル説明つき）
aim2 --ai-help

# 入力・出力単価（$/M tokens）を表示（OpenRouter Models API またはローカル 0$）
aim2 --cost
aim2 --cost --model glm-5.3-flash
aim2 --cost --format json --model glm-5.3-flash

# 人間向けヘルプ表示
aim2 --help

# バージョン表示（設定やAPIキー不要）
aim2 --version
```

### オプション一覧

| オプション                     | 必須 | 説明                                                                                |
| ------------------------------ | ---- | ----------------------------------------------------------------------------------- |
| `-p, --prompt <text>`          | △    | プロンプト文字列。複数指定時は `--parallel` が必要。省略時は標準入力から読む        |
| `-m, --model <alias>`          | -    | 利用するモデル略記（`models.json` のキー。省略時は `default`）                      |
| `--parallel`                   | -    | 複数の `--prompt` を並列に実行する                                                  |
| `--jobs <number>`              | -    | 並列実行数（1〜10、省略時: 4。`--parallel` 専用）                                   |
| `--format <markdown\|json>`    | -    | 出力形式。未指定かつ単発時は本文のみ、`--parallel` 時は markdown、`json` は配列形式 |
| `--cost`                       | -    | 指定モデルの入力・出力単価（$/M tokens）を表示して終了（OpenRouter, Ollama 対応）   |
| `--trace-tool <name>`          | -    | トレースログの分類フォルダ名（デフォルト: `aim2-cli`）                              |
| `--session-id <id>`            | -    | ローカルな会話継続用 session ID。省略時は自動発行し、標準エラーへ表示する           |
| `--thread-id <id>`             | -    | `--session-id` の互換エイリアス                                                     |
| `--full-content-names <names>` | -    | ディレクトリ `@path` で内容を含めるファイル名のカンマ区切り                         |
| `--list-models`                | -    | 利用可能なモデル略記・プロバイダ・モデルID一覧を表示                                |
| `--ai-help`                    | -    | エージェント向けに使い方・モデル一覧・説明を表示                                    |
| `-v, --version`                | -    | バージョン情報を表示                                                                |
| `-h, --help`                   | -    | 人間向けの使い方を表示                                                              |

### 会話継続（`--session-id`）

各プロンプト実行ではローカルな `session_id` を解決する。`--session-id` を省略した場合は、UTC epoch milliseconds とランダム部からなる固定長 ID を自動発行し、`session_id: ...` を**標準エラー**へ表示する。`--thread-id` は入力互換の別名であり、標準出力・標準エラーの新しい表示ラベルは `session_id` に統一する。標準出力の本文フォーマットは変わらない。

- 同じ `session_id` を次回指定すると、過去の成功ターン（user prompt + assistant response）を `tools/aim2/logs/` から再読込して継続する
- 未知の `session_id` を指定した場合は空の履歴から始まる
- `session_id` は**ローカルログ内の会話単位**であり、プロバイダ固有の会話IDや OpenTelemetry の trace 属性には渡さない
- `--parallel` ではジョブごとに別の `session_id` を自動発行する。標準エラーには `session_id[1]: ...` のように表示され、各IDを指定すればそのジョブだけを後から継続できる
- `--parallel --session-id` と `--parallel --thread-id` は指定できない。複数ジョブを1つの会話履歴へ混在させないためである
- 履歴は自動要約・自動圧縮しないため、長いセッションはモデルのコンテキスト上限に達し得る
- 同じ `session_id` を複数プロセスから同時に使うと、履歴が分岐したように見えることがある

### `@path` によるファイル・ディレクトリ展開

`--prompt` および標準入力の本文から、トークン先頭（行頭または空白直後）の `@path` を検出し、その場でファイル/ディレクトリ内容に展開する。

- 日本語助詞（`@src/foo.tsを要約して`）も実在パス最長一致で適切に分離
- 空白を含むパスは `@"path with spaces"` または `@'path'` で指定可能
- ディレクトリを指定した場合、ツリー構造と配下テキストファイルがインライン展開される
- `--full-content-names` で特定のファイル名のみ内容を含め、他をツリー listing のみに絞り込み可能

### ローカルログとトレース（`logs/`）

新規の成功ログは `tools/aim2/logs/<trace_tool>/<YYYY-MM-DD>/<session-id>.jsonl` へ1行追記する。1セッション・1 trace tool・1日につき1ファイルで、日付をまたぐセッションは同じ ID のファイルを複数の日付ディレクトリへ持つ。`session_id` は固定長の時刻部を含むため、辞書順で概ね時刻順に並ぶ。`trace_tool` はフォルダ分け専用である。

旧形式の `tools/aim2/logs/<trace_tool>/<YYYY-MM-DD>.jsonl` と、現在の未コミット版が作った `thread_id` レコードは読み取り専用で互換検索する。旧ログは移動・書き換えず、新形式のセッションファイルを優先して結合する。旧レコードの応答が欠落している行は履歴へ採用しない。

主な記録項目:

- `prompt`: その回の user prompt 本文（`@path` 展開後）
- `response`: その回の assistant 応答本文
- `session_id`: 単発実行または並列ジョブ1件を後から継続する会話ID
- `batch_id`: `--parallel` 1回に含まれるジョブを横断する相関ID
- `trace.trace_id`: 呼び出し単位の OpenTelemetry 準拠 128bit trace ID

```json
{
  "timestamp": "2026-09-15T04:30:00.000Z",
  "model": "gpt-4o-mini",
  "provider": "openai",
  "prompt": "設計案を3つ出して",
  "response": "案1: ...",
  "cost": null,
  "prompt_tokens": 42,
  "completion_tokens": 91,
  "total_tokens": 133,
  "generation_id": null,
  "user": null,
  "session_id": "s1789446600000-0123456789abcdef0123456789abcdef",
  "batch_id": null,
  "trace": {
    "tool": "aim2-cli",
    "trace_id": "0123456789abcdef0123456789abcdef"
  }
}
```

- `logs/` は git 管理対象外であり、プロンプトだけでなく応答本文も保存される
- 明示した session ID に区切り文字・制御文字・Windows 予約名などが含まれる場合は、安全な base64url ファイル名へ決定的にエンコードする
- ログ追記に失敗しても推論結果自体は返すため、直後の継続履歴にそのターンが載らない場合がある

## ファイル構成

- `src/`
  - `cli.ts` — CLI 引数パース・実行ルーティング
  - `config.ts` — 環境変数・.env 解決、models.json バリデーション
  - `at-path.ts` — `@path` 構文展開・トークン抽出
  - `files.ts` — ファイル/ディレクトリ読込・バイナリ判定
  - `runner.ts` — AI SDK モデル実行エンジン
  - `parallel.ts` — pMap 並列実行プール制御
  - `formatter.ts` — Markdown / JSON 出力整形
  - `logger.ts` — トレースログ（`logs/`）永続化
  - `thread.ts` — session ID 解決・新旧ログからのローカル履歴再構築
  - `errors.ts` — AimError 共通エラー正規化
  - `pricing.ts` — モデル単価取得・計算（`--cost`）
  - `providers/` — 動的プロバイダローダーおよび各プロバイダアダプタ
- `models.json` / `models.json.example` — モデルエイリアス定義
- `.env.example` — 環境変数設定例
- `tests/` — 単体・結合テスト
