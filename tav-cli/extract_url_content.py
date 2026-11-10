r"""Extract content from one or more URLs with a small, opinionated CLI.

This wrapper keeps Tavily-specific tuning inside the file so callers only need
to provide URLs, an optional query, and a high-level detail preset.
Adjust the preset values below when you want different Tavily behavior.
Other scripts in this directory can also import the reusable extraction helper.

PowerShell example:
    python .\tools\tav-cli\extract_url_content.py https://learn.microsoft.com/azure/api-management/api-management-policies --query "policy capabilities" --topic apim_policies

bash example:
    python ./tools/tav-cli/extract_url_content.py https://learn.microsoft.com/azure/api-management/api-management-policies --query "policy capabilities" --topic apim_policies
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Mapping

from tavily.errors import InvalidAPIKeyError

from tav_core import (
    TOPIC_ARG_HELP,
    ExitCode,
    ResultKind,
    RunOutcome,
    build_response_payload,
    create_tavily_client,
    dedupe_preserve_order,
    finalize,
)


DETAIL_PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "extract_depth": "basic",
        "query_chunks_per_source": 2,
    },
    "balanced": {
        "extract_depth": "advanced",
        "query_chunks_per_source": 3,
    },
    "max": {
        "extract_depth": "advanced",
        "query_chunks_per_source": 5,
    },
}

DEFAULT_DETAIL = "balanced"
DEFAULT_OUTPUT_FORMAT = "markdown"
REQUEST_TIMEOUT_SECONDS = 60.0
INCLUDE_IMAGES = False
INCLUDE_FAVICON = False
INCLUDE_USAGE = False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract content from URLs with Tavily using minimal arguments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Role: content. With --topic NAME, writes one Markdown page per URL to\n"
            "<TAVILY_OUTPUT_DIR>/NAME/pages/NNNN-<title>.md (split, one page = one file),\n"
            "indexed by pages/index.json. Omit --topic to print one ResultEnvelope to stdout."
        ),
    )
    parser.add_argument(
        "urls",
        nargs="+",
        help="One or more URLs to extract content from.",
    )
    parser.add_argument(
        "--query",
        help="Optional relevance query for focused extraction.",
    )
    parser.add_argument(
        "--detail",
        choices=sorted(DETAIL_PRESETS),
        default=DEFAULT_DETAIL,
        help="High-level extraction preset. Tavily-specific values are already defined.",
    )
    parser.add_argument(
        "--topic",
        help=TOPIC_ARG_HELP,
    )
    return parser.parse_args(argv)


def resolve_extract_options(detail: str, *, has_query: bool) -> dict[str, Any]:
    preset = DETAIL_PRESETS[detail]
    chunks_per_source = preset["query_chunks_per_source"] if has_query else None
    return {
        "extract_depth": preset["extract_depth"],
        "chunks_per_source": chunks_per_source,
        "format": DEFAULT_OUTPUT_FORMAT,
        "timeout": REQUEST_TIMEOUT_SECONDS,
        "include_images": INCLUDE_IMAGES,
        "include_favicon": INCLUDE_FAVICON,
        "include_usage": INCLUDE_USAGE,
    }


def reorder_results_by_requested_urls(
    results: list[dict[str, Any]], requested_urls: Sequence[str]
) -> list[dict[str, Any]]:
    """Re-sort Tavily's extract results to match ``requested_urls`` order.

    Tavily fetches multiple URLs concurrently and does not guarantee ``results``
    comes back in request order, which otherwise makes the sequential file
    numbering in ``topic_layout.write_content_pages`` unpredictable (a page for
    the 2nd requested URL could land in ``0001-...`` instead of ``0002-...``).
    Items whose ``url`` doesn't match any requested URL verbatim (e.g. a
    redirect changed it) are appended at the end in their original relative
    order rather than dropped.
    """
    by_url: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        by_url.setdefault(item.get("url"), []).append(item)

    ordered: list[dict[str, Any]] = []
    for url in requested_urls:
        bucket = by_url.get(url)
        if bucket:
            ordered.append(bucket.pop(0))
    for bucket in by_url.values():
        ordered.extend(bucket)
    return ordered


def run_extract_request(
    client: Any,
    *,
    urls: Sequence[str],
    query: str | None,
    extract_options: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_urls = dedupe_preserve_order(urls)
    response = client.extract(
        urls=normalized_urls,
        query=query,
        **dict(extract_options),
    )
    results = response.get("results")
    if isinstance(results, list):
        response = {
            **response,
            "results": reorder_results_by_requested_urls(results, normalized_urls),
        }
    return {
        "urls": normalized_urls,
        "options": dict(extract_options),
        "response": response,
    }


def main(argv: Sequence[str] | None = None) -> RunOutcome:
    """Extract URLs and return a ``RunOutcome`` (no I/O; ``finalize()`` emits it).

    ``SUCCESS`` on a completed call, or ``MISSING_API_KEY`` / ``INVALID_API_KEY`` /
    ``RUNTIME_ERROR`` on the corresponding failure. The success outcome carries an
    ``EXTRACT_RESULTS`` result.
    """
    args = parse_args(argv)
    extract_options = resolve_extract_options(args.detail, has_query=bool(args.query))

    try:
        client, config_files = create_tavily_client()
    except ValueError as exc:
        return RunOutcome(exit_code=ExitCode.MISSING_API_KEY, message=str(exc))

    try:
        extraction = run_extract_request(
            client,
            urls=args.urls,
            query=args.query,
            extract_options=extract_options,
        )
    except InvalidAPIKeyError as exc:
        return RunOutcome(
            exit_code=ExitCode.INVALID_API_KEY, message=f"Invalid Tavily API key: {exc}"
        )
    except Exception as exc:
        return RunOutcome(exit_code=ExitCode.RUNTIME_ERROR, message=f"Extraction failed: {exc}")

    payload = build_response_payload(
        script_name=Path(__file__).name,
        request={
            "urls": extraction["urls"],
            "query": args.query,
            "detail": args.detail,
            **extraction["options"],
        },
        response=extraction["response"],
        config_files=config_files,
    )

    return RunOutcome(
        exit_code=ExitCode.SUCCESS,
        topic=args.topic,
        log=payload,
        result_kind=ResultKind.EXTRACT_RESULTS,
        result=extraction["response"].get("results") or [],
    )


if __name__ == "__main__":
    raise SystemExit(finalize(main()))
