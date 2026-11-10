"""`tools/tav-cli`(`tav-cli` パッケージ)をライブラリとして薄くラップし、
Tavily 経由の Web 検索・URL 本文抽出をエージェントのツールとして提供する。

`tav` CLI と異なり結果をファイルに書き出さず、そのままツールの戻り値として
返す(エージェントの文脈にそのまま載せて使わせる用途のため)。

`tavily` パッケージを直接 import せず、`tav_core.create_tavily_client()` で
クライアント生成を隠蔽し、`search_topic` / `extract_url_content` の
`run_*_request` / `resolve_*_options` 純粋関数だけを使う。
CLI 用の副作用シェル(`finalize()` / `emit()` / `topic_layout`)は使わない。
"""

from __future__ import annotations

import json

from langchain_core.tools import tool
from search_topic import (
    DETAIL_PRESETS as SEARCH_DETAIL_PRESETS,
    resolve_search_options,
    run_search_request,
)
from tav_core import create_tavily_client
from tavily.errors import InvalidAPIKeyError

from extract_url_content import (
    DETAIL_PRESETS as EXTRACT_DETAIL_PRESETS,
    resolve_extract_options,
    run_extract_request,
)


def _create_client() -> object:
    """`tav_core` に API キー解決を委譲して Tavily クライアントを生成する。

    tav は環境変数 → プロジェクト設定 `.tav.toml` → グローバル設定 `~/.config/tav/config.toml` の順に解決する。
    `agent.py` の `build_chat_model` が `tools/my-agents/.env` を
    `load_dotenv(ENV_PATH, override=False)` で先に読み込むため、`TAVILY_API_KEY` は
    この時点で `os.environ` に載っており、tav の解決で最優先される。
    """
    try:
        client, _ = create_tavily_client()
    except ValueError as exc:
        # TAVILY_API_KEY が空(.env の設定ミス・環境変数の未セット)
        raise RuntimeError(str(exc)) from exc
    return client


@tool
def tavily_search(
    query: str,
    detail: str = "balanced",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> str:
    """Tavily で Web 検索を行い、結果(title/url/content)のリストをJSON文字列で返す。

    detail は "quick" / "balanced" / "max" のいずれか(既定: balanced)。
    include_domains / exclude_domains でドメイン絞り込みが可能(例: ["example.com"])。
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if detail not in SEARCH_DETAIL_PRESETS:
        available = ", ".join(sorted(SEARCH_DETAIL_PRESETS))
        raise ValueError(f"unknown detail {detail!r}; choose one of: {available}")

    client = _create_client()
    search_options = resolve_search_options(detail)
    try:
        run = run_search_request(
            client,
            query=query,
            search_options=search_options,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )
    except InvalidAPIKeyError as exc:
        raise RuntimeError("Invalid Tavily API key") from exc
    except Exception as exc:
        raise RuntimeError(f"Tavily search failed: {exc}") from exc

    results = run["response"].get("results") or []
    return json.dumps(results, ensure_ascii=False)


@tool
def tavily_extract(
    urls: list[str],
    query: str | None = None,
    detail: str = "balanced",
) -> str:
    """指定したURLの本文をTavilyで抽出し、結果のリストをJSON文字列で返す。

    query を渡すとその関連性でフォーカス抽出できる(省略可)。
    detail は "quick" / "balanced" / "max" のいずれか(既定: balanced)。
    """
    if not urls:
        raise ValueError("urls must not be empty")
    if detail not in EXTRACT_DETAIL_PRESETS:
        available = ", ".join(sorted(EXTRACT_DETAIL_PRESETS))
        raise ValueError(f"unknown detail {detail!r}; choose one of: {available}")

    client = _create_client()
    extract_options = resolve_extract_options(detail, has_query=bool(query))
    try:
        run = run_extract_request(
            client,
            urls=urls,
            query=query,
            extract_options=extract_options,
        )
    except InvalidAPIKeyError as exc:
        raise RuntimeError("Invalid Tavily API key") from exc
    except Exception as exc:
        raise RuntimeError(f"Tavily extract failed: {exc}") from exc

    results = run["response"].get("results") or []
    return json.dumps(results, ensure_ascii=False)
