r"""Map a site with Tavily, fetch page titles, and return an aggregated outline.

This wrapper uses Tavily only for URL discovery and then fetches each mapped page
directly to resolve titles. Callers mainly provide a root URL plus a high-level
detail preset; the preset values below control both Tavily map behavior and the
local title-fetch behavior. Edit the preset table near the top of this file when
you want to change depth, breadth, fetch limits, or concurrency.

PowerShell example:
    python .\tools\tav-cli\map_site_titles.py https://learn.microsoft.com/azure/api-management/ --topic apim_docs

bash example:
    python ./tools/tav-cli/map_site_titles.py https://learn.microsoft.com/azure/api-management/ --topic apim_docs
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from tavily.errors import InvalidAPIKeyError

from tav_core import (
    TOPIC_ARG_HELP,
    ExitCode,
    ResultKind,
    RunOutcome,
    build_response_payload,
    collect_titles,
    create_tavily_client,
    dedupe_preserve_order,
    finalize,
)


DETAIL_PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "map": {
            "max_depth": 1,
            "max_breadth": 20,
            "limit": 20,
            "timeout": 30.0,
            "include_usage": False,
        },
        "titles": {
            "max_workers": 4,
            "timeout_seconds": 10.0,
            "max_bytes": 131072,
        },
    },
    "balanced": {
        "map": {
            "max_depth": 2,
            "max_breadth": 30,
            "limit": 40,
            "timeout": 45.0,
            "include_usage": False,
        },
        "titles": {
            "max_workers": 6,
            "timeout_seconds": 12.0,
            "max_bytes": 196608,
        },
    },
    "max": {
        "map": {
            "max_depth": 3,
            "max_breadth": 40,
            "limit": 80,
            "timeout": 60.0,
            "include_usage": False,
        },
        "titles": {
            "max_workers": 8,
            "timeout_seconds": 15.0,
            "max_bytes": 262144,
        },
    },
}

DEFAULT_DETAIL = "balanced"
DEFAULT_ALLOW_EXTERNAL = False

# Title fetching (TitleParser / fetch_page_title / build_title_from_url /
# collect_titles / PageTitleResult) lives in ``tav_core/page_title.py`` so both
# this script and ``tav_core``'s split-layout title back-fill share one
# implementation. The ``DETAIL_PRESETS["titles"]`` budget below is still applied
# here via ``collect_titles``.


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Map a site with Tavily and fetch each page title with minimal arguments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Role: discovery. With --topic NAME, appends one aggregated URL+title list to\n"
            "<TAVILY_OUTPUT_DIR>/NAME/map/NNNN-<domain>.json (one map = one file, never split).\n"
            "Omit --topic to print one ResultEnvelope to stdout."
        ),
    )
    parser.add_argument(
        "url",
        help="Root URL to map.",
    )
    parser.add_argument(
        "--detail",
        choices=sorted(DETAIL_PRESETS),
        default=DEFAULT_DETAIL,
        help="High-level preset for the Tavily map request and title fetching.",
    )
    parser.add_argument(
        "--instruction",
        help="Optional natural-language focus for Tavily map.",
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


def resolve_map_options(detail: str) -> dict[str, dict[str, Any]]:
    preset = DETAIL_PRESETS[detail]
    return {
        "map": dict(preset["map"]),
        "titles": dict(preset["titles"]),
    }


def run_map_request(
    client: Any,
    *,
    url: str,
    map_options: Mapping[str, Any],
    instruction: str | None,
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
    response = client.map(
        url=url,
        instructions=instruction,
        select_paths=normalized_select_paths or None,
        exclude_paths=normalized_exclude_paths or None,
        select_domains=normalized_select_domains or None,
        exclude_domains=normalized_exclude_domains or None,
        allow_external=allow_external,
        **dict(map_options),
    )
    return {
        "url": url,
        "instruction": instruction,
        "select_paths": normalized_select_paths,
        "exclude_paths": normalized_exclude_paths,
        "select_domains": normalized_select_domains,
        "exclude_domains": normalized_exclude_domains,
        "allow_external": allow_external,
        "options": dict(map_options),
        "response": response,
    }


def summarize_pages(pages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    hostnames = {
        urlparse(page.get("final_url") or page.get("url") or "").netloc
        for page in pages
        if page.get("final_url") or page.get("url")
    }
    titled_count = sum(1 for page in pages if page.get("title_source") == "html")
    fallback_count = sum(1 for page in pages if page.get("title_source") != "html")
    error_count = sum(1 for page in pages if page.get("error"))
    return {
        "total_urls": len(pages),
        "html_title_count": titled_count,
        "fallback_title_count": fallback_count,
        "error_count": error_count,
        "unique_host_count": len({hostname for hostname in hostnames if hostname}),
    }


def main(argv: Sequence[str] | None = None) -> RunOutcome:
    """Map a site, resolve titles, and return a ``RunOutcome`` (no I/O; ``finalize()``
    emits it).

    The success ``result`` is the list of per-page title records (see
    ``PageTitleResult``), carried as ``SITE_PAGES``. Returns ``SUCCESS`` on a
    completed call, or ``MISSING_API_KEY`` / ``INVALID_API_KEY`` / ``RUNTIME_ERROR``
    on the corresponding failure.
    """
    args = parse_args(argv)
    options = resolve_map_options(args.detail)

    try:
        client, config_files = create_tavily_client()
    except ValueError as exc:
        return RunOutcome(exit_code=ExitCode.MISSING_API_KEY, message=str(exc))

    try:
        map_run = run_map_request(
            client,
            url=args.url,
            map_options=options["map"],
            instruction=args.instruction,
            select_paths=args.select_path,
            exclude_paths=args.exclude_path,
            select_domains=args.select_domain,
            exclude_domains=args.exclude_domain,
            allow_external=args.allow_external,
        )
        mapped_urls = dedupe_preserve_order(map_run["response"].get("results") or [])
        pages = collect_titles(mapped_urls, title_options=options["titles"])
    except InvalidAPIKeyError as exc:
        return RunOutcome(
            exit_code=ExitCode.INVALID_API_KEY, message=f"Invalid Tavily API key: {exc}"
        )
    except Exception as exc:
        return RunOutcome(
            exit_code=ExitCode.RUNTIME_ERROR, message=f"Map and title aggregation failed: {exc}"
        )

    payload = build_response_payload(
        script_name=Path(__file__).name,
        request={
            "url": map_run["url"],
            "detail": args.detail,
            "instruction": map_run["instruction"],
            "select_paths": map_run["select_paths"],
            "exclude_paths": map_run["exclude_paths"],
            "select_domains": map_run["select_domains"],
            "exclude_domains": map_run["exclude_domains"],
            "allow_external": map_run["allow_external"],
            "map": map_run["options"],
            "titles": options["titles"],
        },
        response={
            "map": map_run["response"],
            "pages": pages,
            "summary": summarize_pages(pages),
        },
        config_files=config_files,
    )

    return RunOutcome(
        exit_code=ExitCode.SUCCESS,
        topic=args.topic,
        log=payload,
        result_kind=ResultKind.SITE_PAGES,
        result=pages,
        slug=urlparse(args.url).netloc or args.url,
    )


if __name__ == "__main__":
    raise SystemExit(finalize(main()))
