"""Offline tests for result classification, index.md layout and parallel sequence allocation.

Run (stdlib only):
    python -m unittest discover -s tools/awsdocs/tests
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

from awsdocs_core import output, rendering  # noqa: E402
from awsdocs_core.config import OUTPUT_DIR_ENV  # noqa: E402


class ClassifySearchItemTests(unittest.TestCase):
    def test_categories_by_url(self) -> None:
        cases = {
            "https://docs.aws.amazon.com/AmazonS3/latest/userguide/security.html": "",
            "https://aws.amazon.com/s3/faqs/": "",
            "https://aws.amazon.com/blogs/security/how-to-use-bucket-policies": "blog",
            "https://aws.amazon.com/about-aws/whats-new/2025/10/foo/": "whats-new",
            "https://repost.aws/knowledge-center/s3-enforce-modern-tls": "repost",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                category, _, content = rendering.render_search_item(
                    {"title": "T", "url": url, "context": "body"}
                )
                self.assertEqual(category, expected)
                self.assertIn(f"URL: {url}", content)

    def test_skill_entry_has_no_url_line(self) -> None:
        category, title, content = rendering.render_search_item(
            {
                "rank_order": 4,
                "title": "securing-s3-buckets",
                "skill_name": "securing-s3-buckets",
                "skill_description": "Create and secure S3 buckets",
            }
        )
        self.assertEqual(category, "skills")
        self.assertEqual(title, "securing-s3-buckets")
        self.assertIn("Skill: securing-s3-buckets", content)
        self.assertNotIn("URL:", content)


class RenderFetchTests(unittest.TestCase):
    URL = "https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html"

    def test_inserts_url_after_leading_h1(self) -> None:
        _, title, content = rendering.render_fetch_item(self.URL, "# What is Amazon S3?\n\nBody\n")
        self.assertEqual(title, "What is Amazon S3?")
        self.assertEqual(content, f"# What is Amazon S3?\n\nURL: {self.URL}\n\nBody\n")

    def test_truncated_page_keeps_toc_and_gets_header_on_top(self) -> None:
        markdown = "Table of Contents:\n- What is Amazon S3? (char 0-34945)\n\n# What is Amazon S3?\n\nBody"
        _, title, content = rendering.render_fetch_item(
            self.URL, markdown, notes=["Truncated at char 10000 of 34946."]
        )
        self.assertEqual(title, "What is Amazon S3?")
        self.assertTrue(content.startswith(f"# What is Amazon S3?\n\nURL: {self.URL}\n> Truncated"))
        self.assertIn("Table of Contents:\n- What is Amazon S3? (char 0-34945)", content)

    def test_redirect_warning_is_in_header(self) -> None:
        target = "https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html"
        _, _, content = rendering.render_fetch_item(
            "https://docs.aws.amazon.com/AmazonS3/latest/userguide/nope.html",
            "# What is Amazon S3?\n\nBody",
            redirected_url=target,
        )
        head = "\n".join(content.splitlines()[:5])
        self.assertIn(f"> Warning: redirected to {target}", head)

    def test_title_falls_back_to_url_segment(self) -> None:
        _, title, _ = rendering.render_fetch_item(self.URL, "ocol over SSL and more text")
        self.assertEqual(title, "Welcome.html")


class AvailabilityTableTests(unittest.TestCase):
    def test_single_region_flat_status(self) -> None:
        result = {"service_apis": {"Lambda+Invoke": "isAvailableIn"}, "next_token": None}
        headers, rows = rendering.availability_rows(result, ["ap-northeast-1"])
        self.assertEqual(headers, ["API", "ap-northeast-1"])
        self.assertEqual(rows, [["Lambda+Invoke", "isAvailableIn"]])

    def test_single_region_status_object(self) -> None:
        result = {"products": {"Glue Jobs": {"status": "isAvailableIn"}}}
        _, rows = rendering.availability_rows(result, ["ap-northeast-1"])
        self.assertEqual(rows, [["Glue Jobs", "isAvailableIn"]])

    def test_multi_region(self) -> None:
        result = {
            "products": {
                "AWS Lambda": {
                    "ap-northeast-1": {"status": "isAvailableIn"},
                    "us-east-1": {"status": "isPlannedIn"},
                }
            }
        }
        headers, rows = rendering.availability_rows(result, ["ap-northeast-1", "us-east-1"])
        self.assertEqual(headers, ["Product", "ap-northeast-1", "us-east-1"])
        self.assertEqual(rows, [["AWS Lambda", "isAvailableIn", "isPlannedIn"]])

    def test_empty(self) -> None:
        _, rows = rendering.availability_rows({"cfn_resources": {}}, ["us-east-1"])
        self.assertEqual(rows, [])


class WriteQueryResultsTests(unittest.TestCase):
    def test_categories_go_to_subfolders_and_index_sections(self) -> None:
        with TemporaryDirectory() as tmp:
            os.environ[OUTPUT_DIR_ENV] = tmp
            try:
                index = output.write_query_results(
                    "s3 security",
                    [
                        ("blog", "A blog", "b"),
                        ("", "A doc", "dd"),
                        ("skills", "a-skill", "sss"),
                        ("repost", "A post", "p"),
                    ],
                    warnings=["0002.md: redirected"],
                    errors=["https://example.com/x: invalid_url"],
                )
            finally:
                os.environ.pop(OUTPUT_DIR_ENV, None)
            folder = index.parent
            self.assertTrue((folder / "blog" / "0001.md").exists())
            self.assertTrue((folder / "0002.md").exists())
            self.assertTrue((folder / "skills" / "0003.md").exists())
            self.assertTrue((folder / "repost" / "0004.md").exists())
            text = index.read_text(encoding="utf-8")
        self.assertLess(text.index("## Docs"), text.index("## Blog"))
        self.assertLess(text.index("## re:Post"), text.index("## Skills"))
        self.assertIn("- [A doc](0002.md) (2 chars)", text)
        self.assertIn("- [a-skill](skills/0003.md) (3 chars)", text)
        self.assertIn("## Warnings\n- 0002.md: redirected", text)
        self.assertIn("## Errors\n- https://example.com/x: invalid_url", text)

    def test_unknown_category_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            os.environ[OUTPUT_DIR_ENV] = tmp
            try:
                with self.assertRaises(ValueError):
                    output.write_query_results("x", [("qa", "T", "c")])
            finally:
                os.environ.pop(OUTPUT_DIR_ENV, None)


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
