r"""Search with Tavily and then extract content from the discovered URLs.

This script composes the reusable search helper from search_topic.py and the
reusable extraction helper from extract_url_content.py. Callers only provide a
query, an optional detail preset, and optional domain filters. The preset for
this pipeline is resolved inside this file into concrete Tavily arguments
before the helper functions are called.

PowerShell example:
    python .\tools\tav-cli\search_extract_topic.py "Azure API Management policy expressions limitations" --topic extract_apim_policy_limitations

bash example:
    python ./tools/tav-cli/search_extract_topic.py "Azure API Management policy expressions limitations" --topic extract_apim_policy_limitations
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tavily.errors import InvalidAPIKeyError

from extract_url_content import run_extract_request
from search_topic import run_search_request
from tav_core import (
    TOPIC_ARG_HELP,
    ExitCode,
    ResultKind,
    RunOutcome,
    TopicArtifact,
    build_response_payload,
    create_tavily_client,
    dedupe_preserve_order,
    finalize,
)


MAX_EXTRACT_URLS = 20
DETAIL_PRESETS: dict[str, dict[str, dict[str, Any]]] = {
    "quick": {
        "search": {
            "search_depth": "fast",
            "topic": "general",
            "max_results": 5,
            "chunks_per_source": 2,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
            "timeout": 60.0,
        },
        "extract": {
            "extract_depth": "basic",
            "chunks_per_source": 2,
            "format": "markdown",
            "timeout": 60.0,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
        },
    },
    "balanced": {
        "search": {
            "search_depth": "advanced",
            "topic": "general",
            "max_results": 5,
            "chunks_per_source": 3,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
            "timeout": 60.0,
        },
        "extract": {
            "extract_depth": "advanced",
            "chunks_per_source": 3,
            "format": "markdown",
            "timeout": 60.0,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
        },
    },
    "max": {
        "search": {
            "search_depth": "advanced",
            "topic": "general",
            "max_results": 8,
            "chunks_per_source": 5,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
            "timeout": 60.0,
        },
        "extract": {
            "extract_depth": "advanced",
            "chunks_per_source": 5,
            "format": "markdown",
            "timeout": 60.0,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
        },
    },
}
DEFAULT_DETAIL = "balanced"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search with Tavily and extract content from the resulting URLs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Roles: discovery + content. With --topic NAME, keeps BOTH halves: the search\n"
            "menu -> <topic>/search/NNNN-<query>.json, and the extracted bodies ->\n"
            "<topic>/pages/NNNN-<title>.md (+ pages/index.json). Omit --topic to print one\n"
            "ResultEnvelope (the extracted content) to stdout."
        ),
    )
    parser.add_argument(
        "query",
        help="Search query to run, and also the relevance query for extraction.",
    )
    parser.add_argument(
        "--detail",
        choices=sorted(DETAIL_PRESETS),
        default=DEFAULT_DETAIL,
        help="High-level preset shared by the search and extraction steps.",
    )
    parser.add_argument(
        "--include-domain",
        action="append",
        default=[],
        help="Optional domain to include. Repeat to allow multiple domains.",
    )
    parser.add_argument(
        "--exclude-domain",
        action="append",
        default=[],
        help="Optional domain to exclude. Repeat to exclude multiple domains.",
    )
    parser.add_argument(
        "--topic",
        help=TOPIC_ARG_HELP,
    )
    return parser.parse_args(argv)


def resolve_pipeline_options(detail: str, *, has_query: bool) -> dict[str, dict[str, Any]]:
    preset = DETAIL_PRESETS[detail]
    extract_options = dict(preset["extract"])
    if not has_query:
        extract_options["chunks_per_source"] = None
    return {
        "search": dict(preset["search"]),
        "extract": extract_options,
    }


def select_urls(search_response: dict[str, Any]) -> list[str]:
    results = search_response.get("results") or []
    urls = [result.get("url", "") for result in results if isinstance(result, dict)]
    return dedupe_preserve_order(urls)[:MAX_EXTRACT_URLS]


def main(argv: Sequence[str] | None = None) -> RunOutcome:
    """Search, extract the discovered URLs, and return a ``RunOutcome`` (no I/O;
    ``finalize()`` emits it).

    Returns ``SUCCESS`` when extraction ran; ``EMPTY_RESULT`` when the search
    produced no URLs to extract (``result`` is then an empty list);
    ``MISSING_API_KEY`` / ``INVALID_API_KEY`` / ``RUNTIME_ERROR`` on failure. The
    data outcome carries ``EXTRACT_RESULTS``.
    """
    args = parse_args(argv)
    pipeline_options = resolve_pipeline_options(args.detail, has_query=bool(args.query))

    try:
        client, config_files = create_tavily_client()
    except ValueError as exc:
        return RunOutcome(exit_code=ExitCode.MISSING_API_KEY, message=str(exc))

    try:
        search_run = run_search_request(
            client,
            query=args.query,
            search_options=pipeline_options["search"],
            include_domains=args.include_domain,
            exclude_domains=args.exclude_domain,
        )
        selected_urls = select_urls(search_run["response"])
        extraction = None
        if selected_urls:
            extraction = run_extract_request(
                client,
                urls=selected_urls,
                query=args.query,
                extract_options=pipeline_options["extract"],
            )
    except InvalidAPIKeyError as exc:
        return RunOutcome(
            exit_code=ExitCode.INVALID_API_KEY, message=f"Invalid Tavily API key: {exc}"
        )
    except Exception as exc:
        return RunOutcome(
            exit_code=ExitCode.RUNTIME_ERROR, message=f"Search and extract failed: {exc}"
        )

    exit_code = ExitCode.SUCCESS if selected_urls else ExitCode.EMPTY_RESULT

    payload = build_response_payload(
        script_name=Path(__file__).name,
        request={
            "query": search_run["query"],
            "detail": args.detail,
            "include_domains": search_run["include_domains"],
            "exclude_domains": search_run["exclude_domains"],
            "selected_url_limit": MAX_EXTRACT_URLS,
            "search": pipeline_options["search"],
            "extract": pipeline_options["extract"] if extraction else None,
        },
        response={
            "search": search_run["response"],
            "selected_urls": selected_urls,
            "extract": extraction["response"] if extraction else None,
        },
        config_files=config_files,
    )

    return RunOutcome(
        exit_code=exit_code,
        topic=args.topic,
        log=payload,
        result_kind=ResultKind.EXTRACT_RESULTS,
        result=(extraction["response"].get("results") or []) if extraction else [],
        # Keep the discovery half too: file the search menu under <topic>/search/.
        discovery=TopicArtifact(
            result_kind=ResultKind.SEARCH_RESULTS,
            result=search_run["response"].get("results") or [],
            slug=args.query,
        ),
        message="Search returned no URLs to extract."
        if exit_code is ExitCode.EMPTY_RESULT
        else None,
    )


if __name__ == "__main__":
    raise SystemExit(finalize(main()))
