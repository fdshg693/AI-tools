---
name: aim-lib
description: "`tools/aim` のグローバルインストール済み Python 実装をライブラリとして使い、OpenRouter 経由で AI モデルへ単発リクエストを送る方法を説明する。Python コードからプロンプトを送信したい、モデル略記を解決したい、応答本文を取り出したい場合に使う。CLI コマンドを実行する場合は `aim-cli` を使う。"
meta:
  tag: []
  requires_repo_tools: tools/aim
  requires_env: OPENROUTER_API_KEY
  dependencies: aim-cli, python>=3.11
  requires_install: tools/aim (uv tool install --editable tools/aim)
  requires_hooks: none
  requires_skills: none
  status: stable
  description: no description
  version: 1.0.9
---

# aim を Python ライブラリとして使う

`tools/aim` は現在、独立した `aim` Python パッケージではなく、`aim_cli` モジュールとして配布されている。ライブラリ利用では `aim` コマンドや `aim_cli.main()` を呼ばず、`aim_cli` が提供する薄いラッパー（`create_client` / `call` / `call_async` / `get_model_cost` / `estimate_prompt_tokens` / `prompt_cost_usd` / `AimError`）を使う。**`openrouter` を直接 import しない** — `openrouter` への依存はパッケージの依存関係にも追加しない。理由は2つ。

- `aim_cli` 側だけが `openrouter` に依存する構成にすることで、利用側パッケージの依存を `aim-cli` 1つに絞れる
- ログ記録（`logs/<trace.tool>/<日付>.jsonl` への追記）が `call`/`call_async` の内部で行われるため、将来 `aim_cli` にログ処理を追加・変更しても、利用側は変更なしにその恩恵を受けられる

## 前提条件

- `tools/aim` がグローバル環境にインストール済みであること（README の前提どおり `uv tool install --editable tools/aim`）
- Python 3.11 以上を使うこと
- `OPENROUTER_API_KEY` が環境変数、または `tools/aim/.env` に設定済みであること。環境変数が優先される
- 未インストール・API キー未設定の場合、このスキルでインストールやキー発行を行わず、`tools/aim/README.md` のセットアップ手順を案内する

## 基本パターン（同期）

```python
from aim_cli import MODELS, create_client, call


def ask_aim(prompt: str, model: str = "mini-m3") -> str:
    if not prompt.strip():
        raise ValueError("prompt must not be empty")

    try:
        model_id = MODELS[model]
    except KeyError as e:
        available = ", ".join(sorted(MODELS))
        raise ValueError(f"unknown model {model!r}; choose one of: {available}") from e

    with create_client() as client:
        return call(client, model_id, prompt)


print(ask_aim("フランスの首都は？"))
```

モデル略記を OpenRouter の実 ID に変換するため、`MODELS[model]` を使う。`MODELS` は `tools/aim/models.json` から読み込まれる。略記の一覧をここに複製しない。利用可能な値は `aim --list-models` または `sorted(MODELS)` で確認する。`mini-m3` を通常の既定値とし、単純な下書きや定型変換だけなら `gpt-120b`、より高い精度・推論力が必要なら `glm-5.2` または `gpt-luna` に切り替える。

## 非同期（並列実行）で使う

`aim_cli.create_client()` が返すクライアントは、同期版の `call()` に加えて非同期版の `call_async()` からも同じクライアントで使い回せる。複数プロンプトを並列に投げたい場合、CLIを複数プロセス/スレッドで叩く代わりに、単一プロセス・単一イベントループ上で `asyncio.gather` を使えばOSスレッドを使わずに並行実行できる。

```python
import asyncio

from aim_cli import MODELS, create_client, call_async


async def ask_aim_many(prompts: list[str], model: str = "mini-m3", max_concurrency: int = 4) -> list[str]:
    model_id = MODELS[model]
    semaphore = asyncio.Semaphore(max_concurrency)

    async def one(client, prompt: str) -> str:
        async with semaphore:
            return await call_async(client, model_id, prompt)

    async with create_client() as client:
        return await asyncio.gather(*(one(client, p) for p in prompts))


print(asyncio.run(ask_aim_many(["フランスの首都は？", "日本の首都は？"])))
```

- 同じクライアントを `async with` 1つで開き、複数の `call_async` 呼び出しで使い回す（コネクションプールが再利用され、リクエストごとに新規プロセス/新規コネクションを作らずに済む）
- 同時実行数の上限は `ThreadPoolExecutor(max_workers=...)` ではなく `asyncio.Semaphore(...)` で制御する。`config.toml` の `jobs` のような同時実行数設定は、この `Semaphore` の初期値にそのまま渡せる
- 呼び出し元が同期コードの場合は `asyncio.run(...)` の中に非同期処理を閉じ込める
- 単発・逐次呼び出ししかしないなら同期版（`call`）で十分。非同期版（`call_async`）は「複数リクエストを並列に送りたい」場合にのみ選ぶ

## trace_idを取得する（呼び出し元の処理単位と紐づけたい場合）

`call`/`call_async`は呼び出しごとにOTel準拠のtrace_id（32桁hex）を自動生成し、OpenRouterへの送信・`logs/<trace.tool>/<日付>.jsonl`への記録の両方に使う。`return_trace_id=True`を渡すと戻り値が`(応答テキスト, trace_id)`のタプルになり、呼び出し元が自身の処理単位（対象ファイルパス、DBレコードなど）とtrace_idを紐づけて保存できる。Grafana Cloud連携（Broadcast機能）を有効化している場合、このtrace_idがGrafana Cloud側のTrace IDと一致するため、後からTempoで該当トレースを検索できる。

```python
from aim_cli import create_client, call

with create_client() as client:
    answer, trace_id = call(client, model_id, prompt, return_trace_id=True)
```

`trace_id`を明示的に指定したい場合（例: 呼び出し元が既に発行済みのtrace idにネストさせたい）は、`trace={"trace_id": "..."}`をそのまま渡せばよい（指定時は自動生成されず、渡した値がそのまま使われる）。

## 入力・出力単価

`get_model_cost` はチャット呼び出しをせず、OpenRouter Models API から最悪ケースの単価（`$/M tokens`）を返す。略記（`models.json`）でも OpenRouter モデルIDでもよい。`:free` は 0。API キーは不要。

```python
from aim_cli import get_model_cost, estimate_prompt_tokens, prompt_cost_usd

cost = get_model_cost("gpt-luna")
print(cost.prompt_per_million, cost.completion_per_million)

tokens = estimate_prompt_tokens(prompt)  # tokenizerなし。1 token ≈ 4 chars（切り上げ）
usd = prompt_cost_usd(cost, tokens)  # 入力のみ。出力は含めない
```

複数プロンプトの合計は `get_model_cost` を1回だけ呼び、各テキストのトークンを足してから `prompt_cost_usd` する。単発なら `estimate_prompt_cost_usd(model, text)`。`aim_pricing` は import しない。

## エラー処理

API 呼び出しをアプリケーション内で扱う場合は、`aim_cli.AimError` を捕捉して呼び出し元へ伝播する（内部の `openrouter.errors.OpenRouterError` は `AimError` にラップされるため、呼び出し側は `openrouter` を import しなくてよい）。`resolve_api_key()`（`create_client()` が内部で呼ぶ）は API キーがないと CLI 用にメッセージを出して `SystemExit` するため、ライブラリとして独自のエラー契約が必要なら、呼び出し前に API キーを検証するか、キー解決処理をアプリケーション側で行う。

```python
from aim_cli import AimError


try:
    answer = ask_aim(prompt, model="glm-5.2")
except AimError as e:
    # 401 / 402 / 429 など。必要に応じて再試行・フォールバックする
    raise RuntimeError("OpenRouter API request failed") from e
```

単価取得（`get_model_cost`）の失敗は `AimPricingError`（ネットワーク・404・応答形式）。`AimError` とは別。

## CLI 版との違い

- ライブラリ版は `aim` コマンドを起動せず、Python プロセス内で呼び出す
- 標準入力・標準出力・`argparse` は使わない。戻り値の文字列を呼び出し元で処理する
- `call`/`call_async` はCLI版と同じ `logs/<trace.tool>/<日付>.jsonl` への監査ログ追記を内部で行う（呼び出し元が明示的にログを書く必要はない）
- このツールの契約は user メッセージ 1件の単発呼び出しであり、system プロンプト・マルチターン・エージェント機能は扱わない
- プロンプト内の `@path` 展開と `--parallel` ファンアウトは CLI 専用。ライブラリの `call` / `call_async` は受け取った文字列をそのまま送る
- 入力・出力単価は `get_model_cost` で取る（略記または OpenRouter モデルID）。`pricing` のベース値と `overrides` の最大値（`$/M tokens`）。`:free` は 0。Models API は認証不要
- 入力テキストの概算USDは `estimate_prompt_tokens` + `prompt_cost_usd`（出力は含めない）。複数件は単価取得を1回にする

クライアントは必ず `with`（非同期なら `async with`）ブロックで使う。API キーやプロンプトを例外メッセージ・標準出力・不要なログへ出力しない。`openrouter` パッケージを直接 import する必要はなく、依存関係にも追加しない — `aim_cli` の `create_client`/`call`/`call_async`/`get_model_cost`/`estimate_prompt_tokens`/`prompt_cost_usd`/`AimError`/`AimPricingError` のみで完結させる。
