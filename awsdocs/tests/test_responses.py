"""Offline tests for MCP response normalization, fetch stitching and rate-limit detection.

Run (stdlib only):
    python -m unittest discover -s tools/awsdocs/tests
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent
sys.path.insert(0, str(SRC))

import awsdocs_cli  # noqa: E402
from awsdocs_core import client, responses  # noqa: E402


def fake_result(text: str | None, *, is_error: bool = False):
    blocks = [] if text is None else [SimpleNamespace(text=text)]
    return SimpleNamespace(content=blocks, is_error=is_error, structured_content=None)


class UnwrapTests(unittest.TestCase):
    def test_success_returns_inner_content(self) -> None:
        body = {"content": {"result": [{"title": "T"}]}}
        self.assertEqual(responses.unwrap(fake_result(json.dumps(body))), body["content"])

    def test_error_message_raises_tool_error(self) -> None:
        body = {
            "errorMessage": "Error executing tool read_documentation: All 1 URL(s) must be from ..."
        }
        with self.assertRaises(responses.ToolResponseError) as ctx:
            responses.unwrap(fake_result(json.dumps(body)))
        self.assertIn("must be from", str(ctx.exception))

    def test_no_content_block_raises_empty(self) -> None:
        with self.assertRaises(responses.EmptyResponseError):
            responses.unwrap(fake_result(None))

    def test_non_json_raises_tool_error(self) -> None:
        with self.assertRaises(responses.ToolResponseError):
            responses.unwrap(fake_result("not json"))


class ChunkBodyTests(unittest.TestCase):
    def test_strips_toc_preamble(self) -> None:
        item = {
            "content": "Table of Contents:\n- A (char 0-20)\n\nKLMNOPQRST",
            "start_index": 10,
            "end_index": 20,
        }
        self.assertEqual(responses.chunk_body(item), "KLMNOPQRST")

    def test_falls_back_to_whole_content(self) -> None:
        self.assertEqual(responses.chunk_body({"content": "abc", "start_index": 0}), "abc")


class ApplyReadItemTests(unittest.TestCase):
    URL = "https://docs.aws.amazon.com/x.html"

    def test_follow_stitches_chunks(self) -> None:
        state = awsdocs_cli.FetchState(url=self.URL, next_start=0)
        first = {
            "status": "SUCCESS",
            "content": "Table of Contents:\n- A (char 0-15)\n\n0123456789",
            "start_index": 0,
            "end_index": 10,
            "total_length": 15,
            "truncated": True,
        }
        self.assertTrue(awsdocs_cli._apply_read_item(state, first, follow=True))
        self.assertEqual(state.next_start, 10)
        second = {
            "status": "SUCCESS",
            "content": "Table of Contents:\n- A (char 0-15)\n\nabcde",
            "start_index": 10,
            "end_index": 15,
            "total_length": 15,
            "truncated": False,
        }
        self.assertFalse(awsdocs_cli._apply_read_item(state, second, follow=True))
        self.assertTrue(state.content.endswith("0123456789abcde"))
        self.assertEqual(state.content.count("Table of Contents:"), 1)

    def test_error_item(self) -> None:
        state = awsdocs_cli.FetchState(url="https://example.com/x", next_start=0)
        item = {"status": "ERROR", "content": "URL must be from ...", "error_code": "invalid_url"}
        self.assertFalse(awsdocs_cli._apply_read_item(state, item, follow=True))
        self.assertEqual(state.failure_kind, "tool")
        self.assertIn("invalid_url", state.failure)

    def test_throttled_item(self) -> None:
        state = awsdocs_cli.FetchState(url=self.URL, next_start=0)
        awsdocs_cli._apply_read_item(state, {"status": "ERROR", "error_code": "throttled"}, False)
        self.assertEqual(state.failure_kind, "throttled")

    def test_empty_success_is_empty_failure(self) -> None:
        state = awsdocs_cli.FetchState(url=self.URL, next_start=30000)
        awsdocs_cli._apply_read_item(state, {"status": "SUCCESS", "content": ""}, False)
        self.assertEqual(state.failure_kind, "empty")


class RateLimitDetectionTests(unittest.TestCase):
    def test_http_429(self) -> None:
        exc = RuntimeError("boom")
        exc.response = SimpleNamespace(status_code=429)
        self.assertTrue(client.is_rate_limit_error(exc))

    def test_jsonrpc_code_in_cause(self) -> None:
        inner = RuntimeError("x")
        inner.error = SimpleNamespace(code=-32004)
        outer = RuntimeError("wrapped")
        outer.__cause__ = inner
        self.assertTrue(client.is_rate_limit_error(outer))

    def test_message(self) -> None:
        self.assertTrue(client.is_rate_limit_error(RuntimeError("Too many requests")))

    def test_other_errors(self) -> None:
        self.assertFalse(client.is_rate_limit_error(RuntimeError("char 4290-5000")))


class ParserTests(unittest.TestCase):
    def test_unknown_topic_is_rejected(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            awsdocs_cli.main(["search", "lambda", "--topic", "nonsense"])
        self.assertEqual(ctx.exception.code, 2)

    def test_too_many_topics_is_rejected(self) -> None:
        argv = ["search", "q"] + [
            x
            for t in ("general", "cdk_docs", "cloudformation", "troubleshooting")
            for x in ("--topic", t)
        ]
        with self.assertRaises(SystemExit) as ctx:
            awsdocs_cli.main(argv)
        self.assertEqual(ctx.exception.code, 2)

    def test_call_adds_prefix(self) -> None:
        self.assertEqual(awsdocs_cli.resolve_tool_name("list_regions", False), "aws___list_regions")
        self.assertEqual(
            awsdocs_cli.resolve_tool_name("aws___list_regions", False), "aws___list_regions"
        )
        self.assertEqual(awsdocs_cli.resolve_tool_name("other", True), "other")


if __name__ == "__main__":
    unittest.main()
