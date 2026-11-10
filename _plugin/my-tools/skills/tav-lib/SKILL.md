---
name: tav-lib
description: "`tools/tav-cli` のグローバルインストール済み Python 実装をライブラリとして使い、Tavily 経由で Web 検索・URL 本文抽出・サイトマップ・クロール・リサーチを行う方法を説明する。Python コードから Tavily API を呼び出したい、`--detail` プリセットを適用した結果を取り出したい場合に使う。CLI コマンドを実行する場合は `tav-cli` を使う。"
meta:
  tag: []
  requires_repo_tools: tools/tav-cli
  requires_env: TAVILY_API_KEY
  dependencies: tav-cli, python>=3.11
  requires_install: tools/tav-cli (uv tool install --editable tools/tav-cli)
  requires_hooks: none
  requires_skills: none
  status: stable
  description: no description
  version: 1.0.5
---

# tav-cli を Python ライブラリとして使う

`tools/tav-cli` は、Tavily SDK をプロジェクト固有のプリセットで固定したラッパー群である。パッケージ名は `tav-cli` で、共通実装を `tav_core` パッケージが、各操作（search / extract / map / crawl / research）のラッパーをトップレベルモジュール（`search_topic` / `extract_url_content` 等）が担う。いずれも `pyproject.toml` の `packages` / `py-modules` に含まれるため、`uv tool install --editable tools/tav-cli` 済みなら `from tav_core import ...` / `from search_topic import ...` で import できる。

ライブラリ利用では `tav` コマンドや `tav_cli.main()` を呼ばず、以下の2層だけを使う。

- `tav_core.create_tavily_client()` … 設定解決（環境変数 / `.tav.toml` / グローバル `config.toml`）＋APIキー解決＋`TavilyClient` 生成。クライアント生成を `tav_core` 内部に隠蔽し、利用側は `tavily` パッケージを直接 import しなくてよい
- 各モジュールの `run_*_request(client, ...)` 純粋関数 … `client` を受け取り、Tavily SDK の細かいオプションを `DETAIL_PRESETS` で抽象化したうえで1リクエストを実行し、`dict` を返す。副作用（stdout/stderr/ファイル書き出し）は持たない

`run_*_request` が Tavily SDK のオプションを `DETAIL_PRESETS` + `resolve_*_options` で固定しているため、将来 Tavily SDK の引数が変わっても `tav-cli` 側の修正だけで済み、利用側は変更なしに追従できる。これが「CLI を subprocess で叩く」代わりにライブラリとして使う理由である。

**`tavily` パッケージを直接 import しない** — `TavilyClient` の生成は `create_tavily_client()` が隠蔽する。ただし `tav_core` はエラーラッパーを提供しないため、`tavily.errors.InvalidAPIKeyError` などのエラー型を捕捉する場合のみ例外的に `from tavily.errors import ...` を使う（依存関係に `tavily-python` を追加する必要はなく、`tav-cli` 経由で入る）。`tav_cli` / `topic_layout` / `output` / `run_shell`（`finalize()` / `emit()` / `spawn_detached`）は CLI 用の副作用シェルであり、ライブラリ利用では使わない。

## 前提条件

- `tools/tav-cli` がグローバル環境にインストール済みであること（README の前提どおり `uv tool install --editable tools/tav-cli`）
- Python 3.11 以上を使うこと
- `TAVILY_API_KEY` が環境変数、またはグローバル設定 `~/.config/tav/config.toml` の `api_key` に設定済みであること。`create_tavily_client()` はプロジェクト設定 `.tav.toml` から `api_key` を読まない（詳細は `tools/tav-cli/README.md` の「設定とパス解決」）。設定ファイルが不正なときも `ValueError`（`ConfigError`）を投げる
- 未インストール・API キー未設定の場合、このスキルでインストールやキー発行を行わず、`tools/tav-cli/README.md` のセットアップ手順を案内する

## 基本パターン（同期・search）

```python
from search_topic import DETAIL_PRESETS, resolve_search_options, run_search_request
from tav_core import create_tavily_client


def search_web(query: str, detail: str = "balanced") -> list[dict]:
    if not query.strip():
        raise ValueError("query must not be empty")
    if detail not in DETAIL_PRESETS:
        available = ", ".join(sorted(DETAIL_PRESETS))
        raise ValueError(f"unknown detail {detail!r}; choose one of: {available}")

    # tuple[TavilyClient, str | None] を返す。context manager ではない。
    client, _ = create_tavily_client()
    search_options = resolve_search_options(detail)
    run = run_search_request(
        client,
        query=query,
        search_options=search_options,
        include_domains=None,
        exclude_domains=None,
    )
    return run["response"]["results"]


print(search_web("Microsoft Fabric overview"))
```

- `DETAIL_PRESETS` のキーは `quick` / `balanced` / `max` の3つ。`balanced` を通常の既定値とする
- `resolve_search_options(detail)` は `DETAIL_PRESETS[detail]` に `INCLUDE_ANSWER` 等の固定フラグをマージして返す。`DETAIL_PRESETS[detail]` を直接渡すと固定フラグが漏れるため、必ず `resolve_search_options` を経由する
- `run_search_request` の戻り値は `{"query", "include_domains", "exclude_domains", "options", "response"}` の `dict`。Tavily の生レスポンスは `run["response"]` に入り、検索結果は `run["response"]["results"]`（`list[SearchResultItem]` 相当の `dict`）
- `include_domains` / `exclude_domains` は `None` または host のリスト。`dedupe_preserve_order` で正規化される

検索結果アイテムの型は `tav_core.tavily_types.SearchResultItem`（`title` / `url` / `content` / `score` / `raw_content`）で、実測で確定された `TypedDict` として公開されている。

## 各操作の対応表

Tavily の全操作で同じ2段構成（`create_tavily_client()` → `run_*_request(client, ...)`）を使う。`resolve_*_options` のシグネチャが操作ごとに異なる点に注意。

| 操作     | モジュール            | リクエスト関数                                                                                                                                                                                                                              | オプション解決                                            | 戻り値の `response` に入るもの                                                     |
| -------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| search   | `search_topic`        | `run_search_request`                                                                                                                                                                                                                        | `resolve_search_options(detail)`                          | `{results: list[SearchResultItem], ...}`                                           |
| extract  | `extract_url_content` | `run_extract_request`                                                                                                                                                                                                                       | `resolve_extract_options(detail, has_query=...)`          | `{results: list[ExtractResultItem], failed_results: list[ExtractFailedItem], ...}` |
| map      | `map_site_titles`     | `run_map_request`                                                                                                                                                                                                                           | `resolve_map_options(detail)`（`dict[str, dict]` を返す） | `{results: list[str], ...}`（URL 文字列のリスト）                                  |
| crawl    | `crawl_site_content`  | `run_crawl_request`                                                                                                                                                                                                                         | `resolve_crawl_options(detail, has_query=...)`            | `{results: list[CrawlResultItem], failed_results, ...}`                            |
| research | `research_topic`      | （`run_*_request` 相当の純粋関数ではなく、前景/背景待機を `main()` が担う。ライブラリ利用では `client.research()` / `client.get_research()` を直接呼ぶか、前景待機の契約が必要な場合は `research_topic.main()` 相当のロジックを自前で組む） | —                                                         | `CompletedResearchResponse`                                                        |

extract の例:

```python
from extract_url_content import DETAIL_PRESETS, resolve_extract_options, run_extract_request
from tav_core import create_tavily_client


def extract_urls(urls: list[str], query: str | None = None, detail: str = "balanced") -> list[dict]:
    if detail not in DETAIL_PRESETS:
        raise ValueError(f"unknown detail {detail!r}")
    client, _ = create_tavily_client()
    extract_options = resolve_extract_options(detail, has_query=bool(query))
    run = run_extract_request(
        client,
        urls=urls,
        query=query,
        extract_options=extract_options,
    )
    return run["response"]["results"]
```

`run_*_request` はいずれも副作用を持たない純粋関数である。CLI 版が `main(argv) -> RunOutcome` を組み立てて `finalize()` で stdout/stderr/ファイルへ書き出すのに対し、ライブラリ版は `dict` を受け取って呼び出し元で処理する。

## 非同期（並列実行）で使う

Tavily SDK は同期 API のみを提供する（`aim_cli.call_async` のようなネイティブ非同期関数はない）。複数リクエストを並列に投げたい場合は、`asyncio.to_thread` で同期の `run_*_request` をスレッド化する。これは OS スレッドを使う点で aim の `call_async`（単一イベントループ上の `asyncio.gather`）と異なるが、Tavily SDK の制約のため仕方がない。

```python
import asyncio

from search_topic import DETAIL_PRESETS, resolve_search_options, run_search_request
from tav_core import create_tavily_client


async def search_many(queries: list[str], detail: str = "balanced", max_concurrency: int = 4) -> list[list[dict]]:
    if detail not in DETAIL_PRESETS:
        raise ValueError(f"unknown detail {detail!r}")
    search_options = resolve_search_options(detail)
    semaphore = asyncio.Semaphore(max_concurrency)

    # クライアントは1つ作り、複数リクエストで使い回す
    client, _ = create_tavily_client()

    async def one(query: str) -> list[dict]:
        async with semaphore:
            run = await asyncio.to_thread(
                run_search_request,
                client,
                query=query,
                search_options=search_options,
                include_domains=None,
                exclude_domains=None,
            )
            return run["response"]["results"]

    return await asyncio.gather(*(one(q) for q in queries))


print(asyncio.run(search_many(["Microsoft Fabric", "Azure Data Factory"])))
```

- 同じクライアントを1つ作り、複数の `run_*_request` 呼び出しで使い回す（プロセス/コネクションを都度作らない）
- 同時実行数の上限は `asyncio.Semaphore(...)` で制御する。`config.toml` の `jobs` のような同時実行数設定があれば、この `Semaphore` の初期値にそのまま渡せる
- 呼び出し元が同期コードの場合は `asyncio.run(...)` の中に非同期処理を閉じ込める
- `run_*_request` が Tavily SDK を同期的に呼ぶため、`asyncio.to_thread` でスレッドプールに逃がさないとイベントループをブロックする。単発・逐次呼び出ししかしないなら同期でそのまま呼べばよい

## エラー処理

API 呼び出しをアプリケーション内で扱う場合は、2段階でエラーを捕捉する。`create_tavily_client()` は API キーが空だと `ValueError` を投げる（CLI 版のような親切な終了メッセージではなく、そのまま例外になる）。`run_*_request` 内の `client.search()` 等は `tavily.errors.InvalidAPIKeyError`（401 等）やその他の `tavily.errors.*` を投げる。

```python
from tavily.errors import InvalidAPIKeyError


try:
    client, _ = create_tavily_client()
except ValueError as exc:
    # TAVILY_API_KEY が空。.env の設定ミス・環境変数の未セット
    raise RuntimeError("Tavily API key is missing") from exc

try:
    run = run_search_request(client, query=query, search_options=search_options)
except InvalidAPIKeyError as exc:
    # 401 等。キーが無効・失効している
    raise RuntimeError("Invalid Tavily API key") from exc
except Exception as exc:
    # 429 / ネットワークエラー / タイムアウト等。必要に応じて再試行・フォールバックする
    raise RuntimeError("Tavily request failed") from exc
```

`tav_core` は `aim_cli.AimError` のようなエラーラッパーを提供しないため、`InvalidAPIKeyError` を型安全に捕捉するには `from tavily.errors import InvalidAPIKeyError` が必要になる。これは aim-lib が「`openrouter` を直接 import しない」としているのと対照的だが、`tav-cli` の設計上、エラー型の隠蔽は `tav_core` の責務外である。`tavily-python` は `tav-cli` の依存として既に入るため、利用側パッケージの依存を追加する必要はない。型安全さを捨ててよければ `except Exception` で広く捕捉してもよい。

## CLI 版との違い

- ライブラリ版は `tav` コマンドを起動せず、Python プロセス内で呼び出す
- 標準入力・標準出力・`argparse` は使わない。`run_*_request` の戻り値 `dict` を呼び出し元で処理する
- `--detail` プリセットは `resolve_*_options(detail)` 経由で使う。CLI 版と同じ `DETAIL_PRESETS` / 固定フラグが適用される
- `finalize()` / `emit()`（`topic_layout` / `output` / `run_shell`）は使わない。これらは `main() -> RunOutcome` から stdout/stderr/ファイルへの副作用を起こす CLI 用の命令的シェルであり、ライブラリ利用では `run_*_request` の純粋関数だけで完結する
- 監査ログ（`<log_dir>/<script>-log.json`）は `finalize()` 経由でのみ書かれるため、ライブラリ利用では書かれない。呼び出し元が監査ログ相当の記録を欲する場合は、`tav_core.build_response_payload()` で `ResponseEnvelope` を構築して自分で保存する
- `--topic` の役割別レイアウト（`search/` / `map/` / `pages/` / `research/`）も `topic_layout` 経由でのみ使われる。ライブラリ利用では呼び出し元が結果を自由に処理する

クライアントは context manager ではないため `with` は使えず、`client, _ = create_tavily_client()` で取り出して使い捨てにする。API キーを例外メッセージ・標準出力・不要なログへ出力しない。`tav_cli` / `topic_layout` / `output` / `run_shell` は直接 import せず、`tav_core.create_tavily_client` + 各モジュールの `run_*_request` / `resolve_*_options` のみで完結させる。
