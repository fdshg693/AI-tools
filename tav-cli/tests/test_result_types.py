r"""Confirm the decided Tavily result TypedDicts match REAL API responses.

The authoritative types live in ``tav_core/tavily_types.py`` (``SearchResultItem``,
``ExtractResultItem``, ``CrawlResultItem``, ``SitePageItem``, ``ResearchSource``,
``CompletedResearchResponse``, ``ExtractFailedItem``). This module proves those
types against real, captured responses in ``fixtures/`` so a drift in the API or
an over-tightened type is caught.

Two layers:
  * Offline (default): structural validation against captured fixtures. Fast,
    deterministic, no network/credits. This is the "確実に正しい型" check.
  * Live (opt-in): set ``TAVILY_LIVE_TESTS=1`` to re-hit the API and validate the
    same types against fresh responses. Set ``TAVILY_LIVE_RESEARCH=1`` to also
    run the slow/expensive research call.

Run (stdlib only, no pytest needed):
    python -m unittest discover -s tools/tav-cli/tests
Or, if pytest is installed, it discovers these unittest cases too.
"""

from __future__ import annotations

import json
import os
import sys
import types
import typing
import unittest
from pathlib import Path
from typing import Any, get_args, get_origin

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES = TESTS_DIR / "fixtures"
SRC = TESTS_DIR.parent
sys.path.insert(0, str(SRC))

from tav_core import (  # noqa: E402
    CompletedResearchResponse,
    CrawlResultItem,
    ExtractFailedItem,
    ExtractResultItem,
    ResearchSource,
    ResultKind,
    SearchResultItem,
    SitePageItem,
    slim_result_item,
)

NoneType = type(None)


# ---------------------------------------------------------------------------
# Structural type checker for the annotation forms our TypedDicts actually use:
# plain scalars, ``X | None`` unions, ``list[X]``, and nested TypedDicts.
# Returns a list of human-readable mismatch strings ([] means it conforms).
# ---------------------------------------------------------------------------
def _matches(value: Any, annotation: Any, path: str) -> list[str]:
    # Nested TypedDict.
    if typing.is_typeddict(annotation):
        return validate_typeddict(value, annotation, path)

    origin = get_origin(annotation)

    # Union, including ``str | None`` (PEP 604) and typing.Optional.
    if origin is typing.Union or isinstance(annotation, types.UnionType):
        for arg in get_args(annotation):
            if not _matches(value, arg, path):
                return []
        return [f"{path}: {value!r} matches none of {annotation}"]

    # list[X]
    if origin is list:
        if not isinstance(value, list):
            return [f"{path}: expected list, got {type(value).__name__}"]
        (item_ann,) = get_args(annotation) or (Any,)
        errors: list[str] = []
        for i, element in enumerate(value):
            errors.extend(_matches(element, item_ann, f"{path}[{i}]"))
        return errors

    if annotation is Any:
        return []
    if annotation is NoneType or annotation is None:
        return [] if value is None else [f"{path}: expected None, got {value!r}"]

    # Plain scalar types. Guard bool (it is a subclass of int) and allow int
    # where float is declared (JSON numbers can come back either way).
    if annotation is bool:
        return (
            []
            if isinstance(value, bool)
            else [f"{path}: expected bool, got {type(value).__name__}"]
        )
    if annotation is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
        return [] if ok else [f"{path}: expected int, got {type(value).__name__}"]
    if annotation is float:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        return [] if ok else [f"{path}: expected float, got {type(value).__name__}"]
    if isinstance(annotation, type):
        ok = isinstance(value, annotation)
        return [] if ok else [f"{path}: expected {annotation.__name__}, got {type(value).__name__}"]

    return [f"{path}: unsupported annotation {annotation!r}"]


def validate_typeddict(value: Any, td: Any, path: str = "item") -> list[str]:
    if not isinstance(value, dict):
        return [f"{path}: expected dict, got {type(value).__name__}"]
    annotations = typing.get_type_hints(td)
    errors: list[str] = []
    for key, ann in annotations.items():
        if key not in value:
            errors.append(f"{path}.{key}: REQUIRED key missing")
            continue
        errors.extend(_matches(value[key], ann, f"{path}.{key}"))
    return errors


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def assert_items(case: unittest.TestCase, items: list[Any], td: Any, *, min_count: int = 1) -> None:
    case.assertGreaterEqual(len(items), min_count, f"expected at least {min_count} item(s)")
    all_errors: list[str] = []
    for i, item in enumerate(items):
        all_errors.extend(validate_typeddict(item, td, f"[{i}]"))
    case.assertEqual(all_errors, [], "type mismatches:\n" + "\n".join(all_errors))


# ---------------------------------------------------------------------------
# Sanity: the checker itself rejects malformed items (so a green suite means
# something). Without this, a no-op checker would also pass.
# ---------------------------------------------------------------------------
class TestCheckerItself(unittest.TestCase):
    def test_missing_required_key_is_caught(self) -> None:
        errors = validate_typeddict(
            {"url": "x", "content": "c", "score": 1.0, "raw_content": None}, SearchResultItem
        )
        self.assertTrue(any("title" in e for e in errors), errors)

    def test_wrong_scalar_type_is_caught(self) -> None:
        bad = {
            "title": "t",
            "url": "u",
            "content": "c",
            "score": "not-a-float",
            "raw_content": None,
        }
        errors = validate_typeddict(bad, SearchResultItem)
        self.assertTrue(any("score" in e for e in errors), errors)

    def test_union_and_list_accept_valid(self) -> None:
        good = {"url": "u", "raw_content": None}  # CrawlResultItem: raw_content is str | None
        self.assertEqual(validate_typeddict(good, CrawlResultItem), [])
        self.assertEqual(_matches(["a", "b"], list[str], "x"), [])
        self.assertTrue(_matches(["a", 1], list[str], "x"))  # non-str element rejected


# ---------------------------------------------------------------------------
# Offline: decided types vs. real captured responses.
# ---------------------------------------------------------------------------
class TestFixtureShapes(unittest.TestCase):
    def test_search_results(self) -> None:
        resp = load_fixture("search_response.json")
        assert_items(self, resp.get("results") or [], SearchResultItem)
        # Pin the doc-divergent fact: raw_content key present, None under our flags.
        for r in resp["results"]:
            self.assertIn("raw_content", r)
            self.assertIsNone(r["raw_content"])
            self.assertNotIn("favicon", r)

    def test_extract_results(self) -> None:
        resp = load_fixture("extract_response.json")
        assert_items(self, resp.get("results") or [], ExtractResultItem)
        for r in resp["results"]:
            self.assertIn("title", r)  # undocumented but relied upon

    def test_extract_failed_results(self) -> None:
        resp = load_fixture("extract_failed_response.json")
        assert_items(self, resp.get("failed_results") or [], ExtractFailedItem)

    def test_crawl_results(self) -> None:
        resp = load_fixture("crawl_response.json")
        assert_items(self, resp.get("results") or [], CrawlResultItem)

    def test_map_results_are_url_strings(self) -> None:
        resp = load_fixture("map_response.json")
        results = resp.get("results") or []
        self.assertGreaterEqual(len(results), 1)
        for url in results:
            self.assertIsInstance(url, str)

    def test_site_pages(self) -> None:
        pages = load_fixture("site_pages.json")
        assert_items(self, pages, SitePageItem)

    def test_research_completed_response(self) -> None:
        resp = load_fixture("research_response.json")
        self.assertEqual(resp.get("status"), "completed")
        self.assertEqual(validate_typeddict(resp, CompletedResearchResponse), [])
        # The script emits ``content`` (markdown str) as the RESEARCH_REPORT result.
        self.assertIsInstance(resp["content"], str)
        assert_items(self, resp.get("sources") or [], ResearchSource)


# ---------------------------------------------------------------------------
# Projection (PLAN.md §4③): what reaches topic files / stdout is the slimmed
# item, NOT the raw *Item. The raw types above stay the validation source of
# truth; here we prove the projection keeps the research-relevant keys and drops
# the noise, run over the SAME real captured fixtures.
# ---------------------------------------------------------------------------
class TestProjection(unittest.TestCase):
    def test_search_projection_drops_raw_content(self) -> None:
        resp = load_fixture("search_response.json")
        for raw in resp["results"]:
            slim = slim_result_item(ResultKind.SEARCH_RESULTS, raw)
            self.assertEqual(set(slim), {"url", "title", "content", "score"})
            self.assertNotIn("raw_content", slim)  # always None under our flags
            # score is retained (decided), and identity/content survive.
            self.assertEqual(slim["url"], raw["url"])

    def test_extract_projection_drops_images(self) -> None:
        resp = load_fixture("extract_response.json")
        for raw in resp["results"]:
            slim = slim_result_item(ResultKind.EXTRACT_RESULTS, raw)
            self.assertEqual(set(slim), {"url", "title", "raw_content"})
            self.assertNotIn("images", slim)

    def test_crawl_projection_is_url_and_body(self) -> None:
        resp = load_fixture("crawl_response.json")
        for raw in resp["results"]:
            slim = slim_result_item(ResultKind.CRAWL_RESULTS, raw)
            self.assertLessEqual(set(slim), {"url", "raw_content"})
            self.assertIn("url", slim)

    def test_site_pages_projection_drops_fetch_metadata(self) -> None:
        for raw in load_fixture("site_pages.json"):
            slim = slim_result_item(ResultKind.SITE_PAGES, raw)
            self.assertLessEqual(set(slim), {"url", "title", "short_title"})
            for dropped in ("title_source", "final_url", "content_type", "status_code", "error"):
                self.assertNotIn(dropped, slim)

    def test_research_report_str_passes_through(self) -> None:
        # A research report is a single str (or failure dict): no per-item projection.
        self.assertEqual(slim_result_item(ResultKind.RESEARCH_REPORT, "# Report"), "# Report")


# ---------------------------------------------------------------------------
# Live (opt-in): re-validate the same types against fresh API responses.
# ---------------------------------------------------------------------------
@unittest.skipUnless(
    os.getenv("TAVILY_LIVE_TESTS") == "1", "set TAVILY_LIVE_TESTS=1 to run live API tests"
)
class TestLiveShapes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tav_core import create_tavily_client

        cls.client, _ = create_tavily_client()

    def test_live_search(self) -> None:
        from search_topic import resolve_search_options, run_search_request

        run = run_search_request(
            self.client,
            query="Microsoft Fabric overview",
            search_options=resolve_search_options("quick"),
            include_domains=["learn.microsoft.com"],
        )
        assert_items(self, run["response"].get("results") or [], SearchResultItem)

    def test_live_extract(self) -> None:
        from extract_url_content import resolve_extract_options, run_extract_request

        run = run_extract_request(
            self.client,
            urls=[
                "https://learn.microsoft.com/en-us/fabric/fundamentals/microsoft-fabric-overview"
            ],
            query="overview",
            extract_options=resolve_extract_options("quick", has_query=True),
        )
        assert_items(self, run["response"].get("results") or [], ExtractResultItem)

    def test_live_crawl(self) -> None:
        from crawl_site_content import resolve_crawl_options, run_crawl_request

        run = run_crawl_request(
            self.client,
            url="https://learn.microsoft.com/en-us/fabric/fundamentals/",
            crawl_options=resolve_crawl_options("quick", has_query=True),
            instruction=None,
            query="overview",
            select_paths=[],
            exclude_paths=[],
            select_domains=[],
            exclude_domains=[],
            allow_external=False,
        )
        assert_items(self, run["response"].get("results") or [], CrawlResultItem)

    @unittest.skipUnless(
        os.getenv("TAVILY_LIVE_RESEARCH") == "1",
        "set TAVILY_LIVE_RESEARCH=1 to run the slow research call",
    )
    def test_live_research(self) -> None:
        import time

        initial = self.client.research(
            input="In one short paragraph, what is the Python GIL?",
            model="mini",
            citation_format="numbered",
            timeout=60.0,
        )
        request_id = initial["request_id"]
        terminal = {"completed", "failed", "cancelled"}
        deadline = time.monotonic() + 180.0
        resp = self.client.get_research(request_id)
        while resp.get("status") not in terminal and time.monotonic() < deadline:
            time.sleep(5.0)
            resp = self.client.get_research(request_id)
        self.assertEqual(resp.get("status"), "completed")
        self.assertEqual(validate_typeddict(resp, CompletedResearchResponse), [])


if __name__ == "__main__":
    unittest.main()
