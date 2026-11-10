r"""Capture real, trimmed Tavily responses as test fixtures.

One call per endpoint with the EXACT options the wrapper scripts use, saving a
few real per-item samples (raw_content truncated to keep fixtures small) to
``tests/fixtures/``. The offline type tests validate against these captured
responses, so they prove the decided TypedDicts match what the live API actually
returned — without hitting the network on every test run.

Re-run this only when you want to refresh the fixtures (it consumes credits, and
the research call takes ~1-2 min).

Run (PowerShell):
    python .\tools\tav-cli\experiments\capture_fixtures.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from crawl_site_content import resolve_crawl_options, run_crawl_request  # noqa: E402
from extract_url_content import resolve_extract_options, run_extract_request  # noqa: E402
from map_site_titles import collect_titles, resolve_map_options, run_map_request  # noqa: E402
from search_topic import resolve_search_options, run_search_request  # noqa: E402
from tav_core import create_tavily_client, dedupe_preserve_order  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
TERMINAL = {"completed", "failed", "cancelled"}
RAW_CAP = 400  # truncate long raw_content / content so fixtures stay small


def trim(item: Any) -> Any:
    if isinstance(item, dict):
        out = {}
        for k, v in item.items():
            if k in {"raw_content", "content"} and isinstance(v, str) and len(v) > RAW_CAP:
                out[k] = v[:RAW_CAP]
            else:
                out[k] = trim(v)
        return out
    if isinstance(item, list):
        return [trim(v) for v in item]
    return item


def save(name: str, payload: Any) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    dest = FIXTURES / name
    dest.write_text(json.dumps(trim(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote {dest.relative_to(FIXTURES.parent.parent)}")


def main() -> None:
    client, _ = create_tavily_client()

    print("search...")
    search = run_search_request(
        client,
        query="Microsoft Fabric overview",
        search_options=resolve_search_options("balanced"),
        include_domains=["learn.microsoft.com"],
    )
    save("search_response.json", search["response"])
    urls = [r["url"] for r in (search["response"].get("results") or [])[:3]]

    print("extract (success)...")
    extract = run_extract_request(
        client,
        urls=urls,
        query="Microsoft Fabric overview",
        extract_options=resolve_extract_options("balanced", has_query=True),
    )
    save("extract_response.json", extract["response"])

    print("extract (failed_results)...")
    failed = run_extract_request(
        client,
        urls=[
            "https://this-domain-should-not-exist-zzz123.example/page",
            "https://httpstat.us/404",
        ],
        query=None,
        extract_options=resolve_extract_options("quick", has_query=False),
    )
    save("extract_failed_response.json", failed["response"])

    print("crawl...")
    crawl = run_crawl_request(
        client,
        url="https://learn.microsoft.com/en-us/fabric/fundamentals/",
        crawl_options=resolve_crawl_options("quick", has_query=True),
        instruction=None,
        query="Microsoft Fabric overview",
        select_paths=[],
        exclude_paths=[],
        select_domains=[],
        exclude_domains=[],
        allow_external=False,
    )
    save("crawl_response.json", crawl["response"])

    print("map + titles...")
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
    save("map_response.json", map_run["response"])
    mapped_urls = dedupe_preserve_order(map_run["response"].get("results") or [])[:5]
    pages = collect_titles(mapped_urls, title_options=map_opts["titles"])
    save("site_pages.json", pages)

    print("research (mini, ~1-2 min)...")
    initial = client.research(
        input="In one short paragraph, what is the Python GIL?",
        model="mini",
        citation_format="numbered",
        timeout=60.0,
    )
    request_id = initial["request_id"]
    deadline = time.monotonic() + 180.0
    resp = client.get_research(request_id)
    while resp.get("status") not in TERMINAL and time.monotonic() < deadline:
        time.sleep(5.0)
        resp = client.get_research(request_id)
    save("research_response.json", resp)

    # Stamp the capture time so fixture freshness is obvious at a glance.
    captured_at = datetime.now().astimezone().isoformat(timespec="seconds")
    stamp = FIXTURES / "captured_at.txt"
    stamp.write_text(
        f"{captured_at}\n"
        "Generated by experiments/capture_fixtures.py. "
        "Records when the fixtures in this directory were captured from the live Tavily API.\n",
        encoding="utf-8",
    )
    print(f"  wrote {stamp.relative_to(FIXTURES.parent.parent)} ({captured_at})")

    print("done.")


if __name__ == "__main__":
    main()
