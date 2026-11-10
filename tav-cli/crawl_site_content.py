r"""Crawl an entire site with Tavily using a small, opinionated CLI.

Use this script when you already know the target site and want Tavily to walk
it directly and return page content in one step. Callers mainly provide a root
URL plus an optional query and detail preset; edit the preset table near the
top of this file when you want to change crawl breadth, depth, or extraction
quality.

PowerShell example:
    python .\tools\tav-cli\crawl_site_content.py https://learn.microsoft.com/azure/api-management/ --query "workspace feature limitations" --topic apim_workspace

bash example:
    python ./tools/tav-cli/crawl_site_content.py https://learn.microsoft.com/azure/api-management/ --query "workspace feature limitations" --topic apim_workspace
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
        "max_depth": 1,
        "max_breadth": 20,
        "limit": 10,
        "extract_depth": "basic",
        "query_chunks_per_source": 2,
    },
    "balanced": {
        "max_depth": 2,
        "max_breadth": 30,
        "limit": 20,
        "extract_depth": "advanced",
        "query_chunks_per_source": 3,
    },
    "max": {
        "max_depth": 3,
        "max_breadth": 40,
        "limit": 40,
        "extract_depth": "advanced",
        "query_chunks_per_source": 5,
    },
}

DEFAULT_DETAIL = "balanced"
DEFAULT_ALLOW_EXTERNAL = False
DEFAULT_OUTPUT_FORMAT = "markdown"
REQUEST_TIMEOUT_SECONDS = 90.0
INCLUDE_IMAGES = False
INCLUDE_FAVICON = False
INCLUDE_USAGE = False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl a site with Tavily and return collected page content.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Role: content. With --topic NAME, writes one Markdown page per crawled URL\n"
            "to <TAVILY_OUTPUT_DIR>/NAME/pages/NNNN-<title>.md (split, one page = one file),\n"
            "indexed by pages/index.json. Omit --topic to print one ResultEnvelope to stdout."
        ),
    )
    parser.add_argument(
        "url",
        help="Root URL to crawl.",
    )
    parser.add_argument(
        "--query",
        help="Optional topic focus. Internally converted into crawl instructions.",
    )
    parser.add_argument(
        "--detail",
        choices=sorted(DETAIL_PRESETS),
        default=DEFAULT_DETAIL,
        help="High-level crawl preset. Tavily-specific values are already defined.",
    )
    parser.add_argument(
        "--instruction",
        help="Optional natural-language crawl instruction to combine with the query focus.",
    )
    parser.add_argument(
        "--select-path",
        action="append",
        default=[],
        help="Optional regex path filter to include. Repeat to allow multiple patterns.",
    )
    parser.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        help="Optional regex path filter to exclude. Repeat to allow multiple patterns.",
    )
    parser.add_argument(
        "--select-domain",
        action="append",
        default=[],
        help="Optional regex domain filter to include. Repeat to allow multiple patterns.",
    )
    parser.add_argument(
        "--exclude-domain",
        action="append",
        default=[],
        help="Optional regex domain filter to exclude. Repeat to allow multiple patterns.",
    )
    parser.add_argument(
        "--allow-external",
        action="store_true",
        default=DEFAULT_ALLOW_EXTERNAL,
        help="Include external-domain URLs discovered during crawl.",
    )
    parser.add_argument(
        "--topic",
        help=TOPIC_ARG_HELP,
    )
    return parser.parse_args(argv)


def combine_instructions(instruction: str | None, query: str | None) -> str | None:
    parts: list[str] = []
    if instruction:
        parts.append(instruction.strip())
    if query:
        parts.append(f"Prioritize content relevant to this topic: {query.strip()}")
    normalized_parts = [part for part in parts if part]
    if not normalized_parts:
        return None
    return "\n".join(normalized_parts)


def resolve_crawl_options(detail: str, *, has_query: bool) -> dict[str, Any]:
    preset = DETAIL_PRESETS[detail]
    return {
        "max_depth": preset["max_depth"],
        "max_breadth": preset["max_breadth"],
        "limit": preset["limit"],
        "extract_depth": preset["extract_depth"],
        "chunks_per_source": preset["query_chunks_per_source"] if has_query else None,
        "format": DEFAULT_OUTPUT_FORMAT,
        "timeout": REQUEST_TIMEOUT_SECONDS,
        "include_images": INCLUDE_IMAGES,
        "include_favicon": INCLUDE_FAVICON,
        "include_usage": INCLUDE_USAGE,
    }


def run_crawl_request(
    client: Any,
    *,
    url: str,
    crawl_options: Mapping[str, Any],
    instruction: str | None,
    query: str | None,
    select_paths: Sequence[str],
    exclude_paths: Sequence[str],
    select_domains: Sequence[str],
    exclude_domains: Sequence[str],
    allow_external: bool,
) -> dict[str, Any]:
    normalized_select_paths = dedupe_preserve_order(select_paths)
    normalized_exclude_paths = dedupe_preserve_order(exclude_paths)
    normalized_select_domains = dedupe_preserve_order(select_domains)
    normalized_exclude_domains = dedupe_preserve_order(exclude_domains)
    combined_instructions = combine_instructions(instruction, query)
    response = client.crawl(
        url=url,
        instructions=combined_instructions,
        select_paths=normalized_select_paths or None,
        exclude_paths=normalized_exclude_paths or None,
        select_domains=normalized_select_domains or None,
        exclude_domains=normalized_exclude_domains or None,
        allow_external=allow_external,
        **dict(crawl_options),
    )
    return {
        "url": url,
        "query": query,
        "instruction": instruction,
        "combined_instructions": combined_instructions,
        "select_paths": normalized_select_paths,
        "exclude_paths": normalized_exclude_paths,
        "select_domains": normalized_select_domains,
        "exclude_domains": normalized_exclude_domains,
        "allow_external": allow_external,
        "options": dict(crawl_options),
        "response": response,
    }


def summarize_crawl_response(response: Mapping[str, Any]) -> dict[str, Any]:
    results = response.get("results") or []
    failed_results = response.get("failed_results") or []
    hostnames = {
        urlparse(result.get("url") or "").netloc
        for result in results
        if isinstance(result, Mapping) and result.get("url")
    }
    return {
        "result_count": len(results),
        "failed_result_count": len(failed_results),
        "unique_host_count": len({hostname for hostname in hostnames if hostname}),
        "response_time": response.get("response_time"),
        "request_id": response.get("request_id"),
    }


def main(argv: Sequence[str] | None = None) -> RunOutcome:
    """Crawl a site and return a ``RunOutcome`` (no I/O; ``finalize()`` emits it).

    ``SUCCESS`` on a completed call, or ``MISSING_API_KEY`` / ``INVALID_API_KEY`` /
    ``RUNTIME_ERROR`` on the corresponding failure. The success outcome carries a
    ``CRAWL_RESULTS`` result.
    """
    args = parse_args(argv)
    crawl_options = resolve_crawl_options(args.detail, has_query=bool(args.query))

    try:
        client, config_files = create_tavily_client()
    except ValueError as exc:
        return RunOutcome(exit_code=ExitCode.MISSING_API_KEY, message=str(exc))

    try:
        crawl_run = run_crawl_request(
            client,
            url=args.url,
            crawl_options=crawl_options,
            instruction=args.instruction,
            query=args.query,
            select_paths=args.select_path,
            exclude_paths=args.exclude_path,
            select_domains=args.select_domain,
            exclude_domains=args.exclude_domain,
            allow_external=args.allow_external,
        )
    except InvalidAPIKeyError as exc:
        return RunOutcome(
            exit_code=ExitCode.INVALID_API_KEY, message=f"Invalid Tavily API key: {exc}"
        )
    except Exception as exc:
        return RunOutcome(exit_code=ExitCode.RUNTIME_ERROR, message=f"Site crawl failed: {exc}")

    payload = build_response_payload(
        script_name=Path(__file__).name,
        request={
            "url": crawl_run["url"],
            "query": crawl_run["query"],
            "detail": args.detail,
            "instruction": crawl_run["instruction"],
            "combined_instructions": crawl_run["combined_instructions"],
            "select_paths": crawl_run["select_paths"],
            "exclude_paths": crawl_run["exclude_paths"],
            "select_domains": crawl_run["select_domains"],
            "exclude_domains": crawl_run["exclude_domains"],
            "allow_external": crawl_run["allow_external"],
            **crawl_run["options"],
        },
        response={
            "crawl": crawl_run["response"],
            "summary": summarize_crawl_response(crawl_run["response"]),
        },
        config_files=config_files,
    )

    return RunOutcome(
        exit_code=ExitCode.SUCCESS,
        topic=args.topic,
        log=payload,
        result_kind=ResultKind.CRAWL_RESULTS,
        result=crawl_run["response"].get("results") or [],
    )


if __name__ == "__main__":
    raise SystemExit(finalize(main()))
