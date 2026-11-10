r"""Map a site with Tavily and then extract content from the discovered URLs.

Use this script when you want to inspect candidate pages first via site mapping
and then fetch content only for the selected mapped URLs. Callers mainly provide
a root URL, an optional query, and a detail preset; edit the preset table near
the top of this file when you want to change map breadth or extraction quality.

PowerShell example:
    python .\tools\tav-cli\map_extract_site_content.py https://learn.microsoft.com/azure/api-management/ --query "workspace feature limitations" --topic extract_apim_workspace

bash example:
    python ./tools/tav-cli/map_extract_site_content.py https://learn.microsoft.com/azure/api-management/ --query "workspace feature limitations" --topic extract_apim_workspace
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tavily.errors import InvalidAPIKeyError

from extract_url_content import run_extract_request
from map_site_titles import run_map_request
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
        "map": {
            "max_depth": 1,
            "max_breadth": 20,
            "limit": 10,
            "timeout": 45.0,
            "include_usage": False,
        },
        "extract": {
            "extract_depth": "basic",
            "query_chunks_per_source": 2,
            "format": "markdown",
            "timeout": 60.0,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
        },
    },
    "balanced": {
        "map": {
            "max_depth": 2,
            "max_breadth": 30,
            "limit": 20,
            "timeout": 60.0,
            "include_usage": False,
        },
        "extract": {
            "extract_depth": "advanced",
            "query_chunks_per_source": 3,
            "format": "markdown",
            "timeout": 60.0,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
        },
    },
    "max": {
        "map": {
            "max_depth": 3,
            "max_breadth": 40,
            "limit": 40,
            "timeout": 75.0,
            "include_usage": False,
        },
        "extract": {
            "extract_depth": "advanced",
            "query_chunks_per_source": 5,
            "format": "markdown",
            "timeout": 75.0,
            "include_images": False,
            "include_favicon": False,
            "include_usage": False,
        },
    },
}
DEFAULT_DETAIL = "balanced"
DEFAULT_ALLOW_EXTERNAL = False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Map a site with Tavily and extract content from the mapped URLs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Roles: discovery + content. With --topic NAME, keeps BOTH halves: the mapped\n"
            "URL inventory -> <topic>/map/NNNN-<domain>.json, and the extracted bodies ->\n"
            "<topic>/pages/NNNN-<title>.md (+ pages/index.json). Omit --topic to print one\n"
            "ResultEnvelope (the extracted content) to stdout."
        ),
    )
    parser.add_argument(
        "url",
        help="Root URL to map.",
    )
    parser.add_argument(
        "--query",
        help="Optional relevance query for the extraction step.",
    )
    parser.add_argument(
        "--detail",
        choices=sorted(DETAIL_PRESETS),
        default=DEFAULT_DETAIL,
        help="High-level preset shared by the map and extraction steps.",
    )
    parser.add_argument(
        "--instruction",
        help="Optional natural-language focus for the map step.",
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
        help="Include external-domain URLs in the mapped result set.",
    )
    parser.add_argument(
        "--topic",
        help=TOPIC_ARG_HELP,
    )
    return parser.parse_args(argv)


def resolve_pipeline_options(detail: str, *, has_query: bool) -> dict[str, dict[str, Any]]:
    preset = DETAIL_PRESETS[detail]
    extract_options = dict(preset["extract"])
    extract_options["chunks_per_source"] = (
        extract_options.pop("query_chunks_per_source") if has_query else None
    )
    return {
        "map": dict(preset["map"]),
        "extract": extract_options,
    }


def select_urls(map_response: dict[str, Any]) -> list[str]:
    urls = map_response.get("results") or []
    return dedupe_preserve_order(urls)[:MAX_EXTRACT_URLS]


def main(argv: Sequence[str] | None = None) -> RunOutcome:
    """Map a site, extract the selected URLs, and return a ``RunOutcome`` (no I/O;
    ``finalize()`` emits it).

    Returns ``SUCCESS`` when extraction ran; ``EMPTY_RESULT`` when the map produced
    no URLs to extract (``result`` is then an empty list); ``MISSING_API_KEY`` /
    ``INVALID_API_KEY`` / ``RUNTIME_ERROR`` on failure. The data outcome carries
    ``EXTRACT_RESULTS``.
    """
    args = parse_args(argv)
    pipeline_options = resolve_pipeline_options(args.detail, has_query=bool(args.query))

    try:
        client, config_files = create_tavily_client()
    except ValueError as exc:
        return RunOutcome(exit_code=ExitCode.MISSING_API_KEY, message=str(exc))

    try:
        map_run = run_map_request(
            client,
            url=args.url,
            map_options=pipeline_options["map"],
            instruction=args.instruction,
            select_paths=args.select_path,
            exclude_paths=args.exclude_path,
            select_domains=args.select_domain,
            exclude_domains=args.exclude_domain,
            allow_external=args.allow_external,
        )
        selected_urls = select_urls(map_run["response"])
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
            exit_code=ExitCode.RUNTIME_ERROR, message=f"Map and extract failed: {exc}"
        )

    exit_code = ExitCode.SUCCESS if selected_urls else ExitCode.EMPTY_RESULT

    payload = build_response_payload(
        script_name=Path(__file__).name,
        request={
            "url": map_run["url"],
            "query": args.query,
            "detail": args.detail,
            "instruction": map_run["instruction"],
            "select_paths": map_run["select_paths"],
            "exclude_paths": map_run["exclude_paths"],
            "select_domains": map_run["select_domains"],
            "exclude_domains": map_run["exclude_domains"],
            "allow_external": map_run["allow_external"],
            "selected_url_limit": MAX_EXTRACT_URLS,
            "map": pipeline_options["map"],
            "extract": pipeline_options["extract"] if extraction else None,
        },
        response={
            "map": map_run["response"],
            "selected_urls": selected_urls,
            "extract": extraction["response"] if extraction else None,
        },
        config_files=config_files,
    )

    mapped_urls = dedupe_preserve_order(map_run["response"].get("results") or [])
    return RunOutcome(
        exit_code=exit_code,
        topic=args.topic,
        log=payload,
        result_kind=ResultKind.EXTRACT_RESULTS,
        result=(extraction["response"].get("results") or []) if extraction else [],
        # Keep the discovery half too: file the mapped URL inventory under <topic>/map/.
        discovery=TopicArtifact(
            result_kind=ResultKind.SITE_PAGES,
            result=[{"url": url} for url in mapped_urls],
            slug=urlparse(map_run["url"]).netloc or map_run["url"],
        ),
        message="Map returned no URLs to extract." if exit_code is ExitCode.EMPTY_RESULT else None,
    )


if __name__ == "__main__":
    raise SystemExit(finalize(main()))
