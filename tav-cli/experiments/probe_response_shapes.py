r"""Probe the REAL shapes of Tavily per-item results, using the exact options
the wrapper scripts use.

Goal: stop treating the Tavily result objects as loose ``dict`` and pin down the
concrete keys + value types we may rely on in downstream scripts. This file is a
disposable lab notebook: it hits the live API once per endpoint with the same
fixed flags the production wrappers use (``resolve_*_options``), then prints, for
every per-item dict, a key -> {observed python types, presence ratio} table.

Run (PowerShell):
    python .\tools\tav-cli\experiments\probe_response_shapes.py

Keep credit usage low: one small call per endpoint, ``quick`` presets where it
matters. Research is probed by a separate script because it is slow/expensive.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from crawl_site_content import resolve_crawl_options, run_crawl_request  # noqa: E402
from extract_url_content import resolve_extract_options, run_extract_request  # noqa: E402
from map_site_titles import resolve_map_options, run_map_request  # noqa: E402
from search_topic import resolve_search_options, run_search_request  # noqa: E402
from tav_core import create_tavily_client  # noqa: E402


def type_name(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, list):
        inner = sorted({type_name(v) for v in value}) or ["<empty>"]
        return f"list[{'|'.join(inner)}]"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def profile_items(items: list[Any]) -> dict[str, Any]:
    """key -> {types: set, present: count}, plus item count + non-dict warning."""
    key_types: dict[str, set[str]] = defaultdict(set)
    key_present: dict[str, int] = defaultdict(int)
    non_dict = 0
    for item in items:
        if not isinstance(item, dict):
            non_dict += 1
            continue
        for key, value in item.items():
            key_types[key].add(type_name(value))
            key_present[key] += 1
    dict_count = len(items) - non_dict
    return {
        "item_count": len(items),
        "non_dict_count": non_dict,
        "keys": {
            key: {
                "types": sorted(key_types[key]),
                "present": key_present[key],
                "always": key_present[key] == dict_count and dict_count > 0,
            }
            for key in sorted(key_types)
        },
    }


def report(label: str, profile: dict[str, Any]) -> None:
    print(f"\n=== {label} ===")
    print(f"items: {profile['item_count']} (non-dict: {profile['non_dict_count']})")
    for key, info in profile["keys"].items():
        flag = (
            "REQUIRED"
            if info["always"]
            else f"optional ({info['present']}/{profile['item_count'] - profile['non_dict_count']})"
        )
        print(f"  {key:18} {flag:24} types={info['types']}")


def report_top_level(label: str, response: dict[str, Any]) -> None:
    print(f"\n--- {label}: top-level keys ---")
    for key in sorted(response):
        print(f"  {key:18} types={type_name(response[key])}")


def main() -> None:
    client, _ = create_tavily_client()
    summary: dict[str, Any] = {}

    # --- search (script flags: no raw_content / images / favicon) ---
    search_opts = resolve_search_options("balanced")
    search = run_search_request(
        client,
        query="Microsoft Fabric overview",
        search_options=search_opts,
        include_domains=["learn.microsoft.com"],
    )
    report_top_level("search", search["response"])
    prof = profile_items(search["response"].get("results") or [])
    report("search results[]", prof)
    summary["search"] = prof

    # --- extract (with query -> chunked raw_content; no images/favicon) ---
    extract_opts = resolve_extract_options("balanced", has_query=True)
    extraction = run_extract_request(
        client,
        urls=[r["url"] for r in (search["response"].get("results") or [])[:3]],
        query="Microsoft Fabric overview",
        extract_options=extract_opts,
    )
    report_top_level("extract", extraction["response"])
    prof = profile_items(extraction["response"].get("results") or [])
    report("extract results[]", prof)
    prof_failed = profile_items(extraction["response"].get("failed_results") or [])
    report("extract failed_results[]", prof_failed)
    summary["extract"] = prof
    summary["extract_failed"] = prof_failed

    # --- crawl (quick preset to limit credits) ---
    crawl_opts = resolve_crawl_options("quick", has_query=True)
    crawl = run_crawl_request(
        client,
        url="https://learn.microsoft.com/en-us/fabric/fundamentals/",
        crawl_options=crawl_opts,
        instruction=None,
        query="Microsoft Fabric overview",
        select_paths=[],
        exclude_paths=[],
        select_domains=[],
        exclude_domains=[],
        allow_external=False,
    )
    report_top_level("crawl", crawl["response"])
    prof = profile_items(crawl["response"].get("results") or [])
    report("crawl results[]", prof)
    summary["crawl"] = prof

    # --- map (results is list[str], not list[dict]) ---
    map_opts = resolve_map_options("quick")
    map_run = run_map_request(
        client,
        url="https://learn.microsoft.com/en-us/fabric/fundamentals/",
        map_options=map_opts["map"],
        instruction=None,
        select_paths=[],
        exclude_paths=[],
        select_domains=[],
        exclude_domains=[],
        allow_external=False,
    )
    report_top_level("map", map_run["response"])
    map_results = map_run["response"].get("results") or []
    print("\n=== map results[] ===")
    print(f"  element types: {sorted({type_name(v) for v in map_results}) or ['<empty>']}")
    print(f"  sample: {map_results[:3]}")
    summary["map_results_types"] = sorted({type_name(v) for v in map_results})

    out = Path(__file__).resolve().parent / "probe_shapes_result.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote machine-readable summary to {out}")


if __name__ == "__main__":
    main()
