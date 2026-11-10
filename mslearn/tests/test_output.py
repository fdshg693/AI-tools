"""Offline tests for fetch URL lines and parallel sequence allocation.

Run (stdlib only):
    python -m unittest discover -s tools/mslearn/tests
"""

from __future__ import annotations

import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent
sys.path.insert(0, str(SRC))

from mslearn_core import output, rendering  # noqa: E402
from mslearn_core.config import OUTPUT_DIR_ENV  # noqa: E402


class RenderFetchUrlTests(unittest.TestCase):
    def test_inserts_url_after_h1(self) -> None:
        url = "https://learn.microsoft.com/azure/search/search-query-odata-search"
        markdown = "# Naming rules (Azure AI Search)\n\nThis section explains the naming...\n"
        _, title, content = rendering.render_fetch_item(url, markdown)
        self.assertEqual(title, "Naming rules (Azure AI Search)")
        self.assertEqual(
            content,
            "# Naming rules (Azure AI Search)\n\n"
            f"URL: {url}\n\n"
            "This section explains the naming...\n",
        )

    def test_leaves_existing_url_line_alone(self) -> None:
        url = "https://learn.microsoft.com/azure/search/search-query-odata-search"
        markdown = (
            "# Naming rules (Azure AI Search)\n\n"
            f"URL: {url}\n\n"
            "This section explains the naming...\n"
        )
        _, _, content = rendering.render_fetch_item(url, markdown)
        self.assertEqual(content, markdown)
        self.assertEqual(content.count("URL:"), 1)

    def test_inserts_url_when_there_is_no_h1(self) -> None:
        url = "https://learn.microsoft.com/azure/search/search-query-odata-search"
        markdown = "This section explains the naming...\n"
        _, title, content = rendering.render_fetch_item(url, markdown)
        self.assertEqual(title, "search-query-odata-search")
        self.assertTrue(content.startswith(f"URL: {url}\n\n"))

    def test_search_item_still_has_url_line(self) -> None:
        _, _, content = rendering.render_search_item(
            {
                "title": "Naming rules",
                "contentUrl": "https://learn.microsoft.com/azure/search/naming",
                "content": "body",
            }
        )
        self.assertIn("URL: https://learn.microsoft.com/azure/search/naming", content)


class SequenceAllocationTests(unittest.TestCase):
    def test_sequential_runs_increment(self) -> None:
        with TemporaryDirectory() as tmp:
            os.environ[OUTPUT_DIR_ENV] = tmp
            try:
                first = output.write_query_results("alpha", [("", "A", "one")])
                second = output.write_query_results("beta", [("", "B", "two")])
            finally:
                os.environ.pop(OUTPUT_DIR_ENV, None)
            self.assertEqual(first.parent.name, "0001-alpha")
            self.assertEqual(second.parent.name, "0002-beta")

    def test_parallel_runs_get_distinct_prefixes(self) -> None:
        labels = [f"query-{i}" for i in range(8)]
        with TemporaryDirectory() as tmp:
            os.environ[OUTPUT_DIR_ENV] = tmp
            try:

                def write_one(label: str) -> str:
                    path = output.write_query_results(label, [("", label, "body")])
                    return path.parent.name

                with ThreadPoolExecutor(max_workers=8) as pool:
                    names = list(pool.map(write_one, labels))
            finally:
                os.environ.pop(OUTPUT_DIR_ENV, None)

        prefixes = [name.split("-", 1)[0] for name in names]
        self.assertEqual(sorted(prefixes), [f"{i:04d}" for i in range(1, 9)])
        self.assertEqual(len(set(prefixes)), 8)


if __name__ == "__main__":
    unittest.main()
