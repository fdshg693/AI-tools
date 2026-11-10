"""`tools/mslearn`(`mslearn_core`)をライブラリとして薄くラップし、
Microsoft Learn / Azure公式ドキュメントの検索・コードサンプル検索・ページ取得を
エージェントのツールとして提供する。

`mslearn` CLIと異なり結果をファイルに書き出さず、そのままツールの戻り値として
返す(エージェントの文脈にそのまま載せて使わせる用途のため)。
"""

from __future__ import annotations

import json

from langchain_core.tools import tool
from mslearn_core import client
from mslearn_core.config import DEFAULT_TIMEOUT


@tool
def mslearn_search(query: str) -> str:
    """Microsoft Learn / Azure公式ドキュメントを検索し、結果(title/content/contentUrl)をJSON文字列で返す。"""
    endpoint = client.resolve_endpoint(None)
    result = client.call_tool(endpoint, DEFAULT_TIMEOUT, "microsoft_docs_search", {"query": query})
    if result.is_error:
        raise RuntimeError(f"microsoft_docs_search failed: {client.content_text(result)}")
    results = (result.structured_content or {}).get("results", [])
    return json.dumps(results, ensure_ascii=False)


@tool
def mslearn_code_search(query: str, language: str | None = None) -> str:
    """Microsoft/Azure公式のコードサンプルを検索し、結果をJSON文字列で返す。languageで言語を絞り込める(例: python)。"""
    endpoint = client.resolve_endpoint(None)
    arguments: dict[str, str] = {"query": query}
    if language:
        arguments["language"] = language
    result = client.call_tool(endpoint, DEFAULT_TIMEOUT, "microsoft_code_sample_search", arguments)
    if result.is_error:
        raise RuntimeError(f"microsoft_code_sample_search failed: {client.content_text(result)}")
    results = (result.structured_content or {}).get("results", [])
    return json.dumps(results, ensure_ascii=False)


@tool
def mslearn_fetch(url: str) -> str:
    """Microsoft Learnのページ1件をMarkdown本文として取得する。"""
    endpoint = client.resolve_endpoint(None)
    result = client.call_tool(endpoint, DEFAULT_TIMEOUT, "microsoft_docs_fetch", {"url": url})
    if result.is_error:
        raise RuntimeError(f"microsoft_docs_fetch failed: {client.content_text(result)}")
    markdown = client.content_text(result)
    if not markdown.strip():
        raise RuntimeError(f"Fetched empty content from {url}")
    return markdown
