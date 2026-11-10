r"""Search the web with Tavily using a small, opinionated CLI.

This wrapper keeps search-depth and result-count tuning inside the file so
callers only need a query, an optional detail preset, and optional domain
filters. Adjust the preset values below when you want different Tavily search
behavior. Other scripts in this directory can import the reusable search helper.

PowerShell example:
    python .\tools\tav-cli\search_topic.py "Microsoft Fabric overview" --topic fabric_overview

bash example:
    python ./tools/tav-cli/search_topic.py "Microsoft Fabric overview" --topic fabric_overview
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
        "search_depth": "fast",
        "max_results": 5,
        "chunks_per_source": 2,
    },
    "balanced": {
        "search_depth": "advanced",
        "max_results": 5,
        "chunks_per_source": 3,
    },
    "max": {
        "search_depth": "advanced",
        "max_results": 8,
        "chunks_per_source": 5,
    },
}

DEFAULT_DETAIL = "balanced"
DEFAULT_TOPIC = "general"
REQUEST_TIMEOUT_SECONDS = 60.0
INCLUDE_ANSWER = False
INCLUDE_RAW_CONTENT = False
INCLUDE_IMAGES = False
INCLUDE_FAVICON = False
INCLUDE_USAGE = False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search the web with Tavily using minimal arguments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Role: discovery. With --topic NAME, appends one aggregated list file to\n"
            "<TAVILY_OUTPUT_DIR>/NAME/search/NNNN-<query>.json (never split per-URL).\n"
            "Omit --topic to print one ResultEnvelope to stdout."
        ),
    )
    parser.add_argument(
        "query",
        help="Search query to send to Tavily.",
    )
    parser.add_argument(
        "--detail",
        choices=sorted(DETAIL_PRESETS),
        default=DEFAULT_DETAIL,
        help="High-level search preset. Tavily-specific values are already defined.",
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


def resolve_search_options(detail: str) -> dict[str, Any]:
    preset = DETAIL_PRESETS[detail]
    return {
        "search_depth": preset["search_depth"],
        "topic": DEFAULT_TOPIC,
        "max_results": preset["max_results"],
        "chunks_per_source": preset["chunks_per_source"],
        "include_answer": INCLUDE_ANSWER,
        "include_raw_content": INCLUDE_RAW_CONTENT,
        "include_images": INCLUDE_IMAGES,
        "include_favicon": INCLUDE_FAVICON,
        "include_usage": INCLUDE_USAGE,
        "timeout": REQUEST_TIMEOUT_SECONDS,
    }


def run_search_request(
    client: Any,
    *,
    query: str,
    search_options: Mapping[str, Any],
    include_domains: Sequence[str] | None = None,
    exclude_domains: Sequence[str] | None = None,
) -> dict[str, Any]:
    normalized_include_domains = dedupe_preserve_order(include_domains or [])
    normalized_exclude_domains = dedupe_preserve_order(exclude_domains or [])
    response = client.search(
        query=query,
        include_domains=normalized_include_domains or None,
        exclude_domains=normalized_exclude_domains or None,
        **dict(search_options),
    )
    return {
        "query": query,
        "include_domains": normalized_include_domains,
        "exclude_domains": normalized_exclude_domains,
        "options": dict(search_options),
        "response": response,
    }


def main(argv: Sequence[str] | None = None) -> RunOutcome:
    """Run a search and return a ``RunOutcome`` (no I/O; ``finalize()`` emits it).

    ``SUCCESS`` on a completed call (even when Tavily returns zero results), or
    ``MISSING_API_KEY`` / ``INVALID_API_KEY`` / ``RUNTIME_ERROR`` on the
    corresponding failure. The success outcome carries a ``SEARCH_RESULTS`` result.
    """
    args = parse_args(argv)
    search_options = resolve_search_options(args.detail)

    try:
        client, config_files = create_tavily_client()
    except ValueError as exc:
        return RunOutcome(exit_code=ExitCode.MISSING_API_KEY, message=str(exc))

    try:
        search_run = run_search_request(
            client,
            query=args.query,
            search_options=search_options,
            include_domains=args.include_domain,
            exclude_domains=args.exclude_domain,
        )
    except InvalidAPIKeyError as exc:
        return RunOutcome(
            exit_code=ExitCode.INVALID_API_KEY, message=f"Invalid Tavily API key: {exc}"
        )
    except Exception as exc:
        return RunOutcome(exit_code=ExitCode.RUNTIME_ERROR, message=f"Search failed: {exc}")

    payload = build_response_payload(
        script_name=Path(__file__).name,
        request={
            "query": search_run["query"],
            "detail": args.detail,
            "include_domains": search_run["include_domains"],
            "exclude_domains": search_run["exclude_domains"],
            **search_run["options"],
        },
        response=search_run["response"],
        config_files=config_files,
    )

    return RunOutcome(
        exit_code=ExitCode.SUCCESS,
        topic=args.topic,
        log=payload,
        result_kind=ResultKind.SEARCH_RESULTS,
        result=search_run["response"].get("results") or [],
        slug=args.query,
    )


if __name__ == "__main__":
    raise SystemExit(finalize(main()))
