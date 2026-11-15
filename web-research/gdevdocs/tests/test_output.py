"""Offline tests for folder layout, Markdown rendering, and exit codes.

Nothing here opens a network connection. Live MCP calls stay out of the suite.
"""

from __future__ import annotations

import os
import sys
import tomllib
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent
sys.path.insert(0, str(SRC))

from gdevdocs_cli import main  # noqa: E402
from gdevdocs_core import output, rendering  # noqa: E402
from gdevdocs_core.client import retries_rate_limit  # noqa: E402
from gdevdocs_core.config import (  # noqa: E402
    API_KEY_ENV,
    CONFIG_HOME_ENV,
    ENDPOINT_ENV,
    EXIT_EMPTY_RESULT,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    EXIT_TOOL_ERROR,
    OUTPUT_DIR_ENV,
)
from gdevdocs_core.environment import ConfigError, load_config_files  # noqa: E402


PARENT = "documents/docs.cloud.google.com/storage/docs/creating-buckets"
PAGE_URL = "https://docs.cloud.google.com/storage/docs/creating-buckets"


def _result(*, structured=None, text="", is_error=False):
    content = [SimpleNamespace(text=text)] if text else []
    return SimpleNamespace(structured_content=structured, content=content, is_error=is_error)


@contextmanager
def _isolated_env(tmp: str, **extra: str):
    """Drop real credentials and pin config/output to `tmp`."""
    keys = (API_KEY_ENV, OUTPUT_DIR_ENV, ENDPOINT_ENV, CONFIG_HOME_ENV)
    saved = {key: os.environ.get(key) for key in keys}
    os.environ.pop(API_KEY_ENV, None)
    os.environ[CONFIG_HOME_ENV] = tmp
    os.environ[OUTPUT_DIR_ENV] = tmp
    for key, value in extra.items():
        os.environ[key] = value
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class RenderingTests(unittest.TestCase):
    def test_search_chunk_url_drops_documents_prefix(self) -> None:
        title, content = rendering.render_search_item(
            {"parent": PARENT, "id": "c1", "content": "Create a bucket."}
        )
        self.assertEqual(title, "creating-buckets")
        self.assertIn(f"URL: {PAGE_URL}", content)
        self.assertIn(f"Parent: {PARENT}", content)
        self.assertIn("Create a bucket.", content)

    def test_fetch_uses_uri_and_keeps_leading_heading(self) -> None:
        title, content = rendering.render_document(
            {
                "title": "Create a bucket",
                "uri": PAGE_URL,
                "content": "# Create a bucket\n\nBody\n",
                "description": "How to create one.",
                "name": PARENT,
            }
        )
        self.assertEqual(title, "Create a bucket")
        self.assertTrue(content.startswith("# Create a bucket\n"))
        self.assertIn(f"URL: {PAGE_URL}", content)
        self.assertIn("How to create one.", content)
        self.assertIn("Body", content)

    def test_answer_writes_text_and_references(self) -> None:
        title, content = rendering.render_answer(
            "what is a bucket",
            {
                "answerText": "A bucket holds objects.",
                "references": [PARENT],
            },
        )
        self.assertEqual(title, "what is a bucket")
        self.assertIn("A bucket holds objects.", content)
        self.assertIn(PARENT, content)

    def test_https_url_becomes_document_name(self) -> None:
        self.assertEqual(rendering.document_name(PAGE_URL), PARENT)
        self.assertEqual(rendering.document_name(PARENT), PARENT)

    def test_scheme_less_uri_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            rendering.document_name("docs.cloud.google.com/storage/docs/creating-buckets")


class WriteResultsTests(unittest.TestCase):
    def test_index_lists_files_with_char_counts(self) -> None:
        with TemporaryDirectory() as tmp:
            os.environ[OUTPUT_DIR_ENV] = tmp
            try:
                index = output.write_query_results(
                    "create a bucket",
                    [("creating-buckets", "hello"), ("second", "abcd")],
                )
            finally:
                os.environ.pop(OUTPUT_DIR_ENV, None)
            folder = index.parent
            self.assertEqual(folder.name, "0001-create-a-bucket")
            self.assertEqual((folder / "0001.md").read_text(encoding="utf-8"), "hello")
            text = index.read_text(encoding="utf-8")
        self.assertIn("- [creating-buckets](0001.md) (5 chars)", text)
        self.assertIn("- [second](0002.md) (4 chars)", text)

    def test_sequential_runs_increment(self) -> None:
        with TemporaryDirectory() as tmp:
            os.environ[OUTPUT_DIR_ENV] = tmp
            try:
                first = output.write_query_results("alpha", [("A", "one")])
                second = output.write_query_results("beta", [("B", "two")])
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
                    path = output.write_query_results(label, [(label, "body")])
                    return path.parent.name

                with ThreadPoolExecutor(max_workers=8) as pool:
                    names = list(pool.map(write_one, labels))
            finally:
                os.environ.pop(OUTPUT_DIR_ENV, None)
        prefixes = [name.split("-", 1)[0] for name in names]
        self.assertEqual(sorted(prefixes), [f"{i:04d}" for i in range(1, 9)])


class EnvironmentTests(unittest.TestCase):
    def test_default_output_dir_anchors_at_git_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            sub = root / "sub"
            sub.mkdir()
            saved = os.environ.get(OUTPUT_DIR_ENV)
            home = os.environ.get(CONFIG_HOME_ENV)
            os.environ.pop(OUTPUT_DIR_ENV, None)
            os.environ[CONFIG_HOME_ENV] = str(root / "no-config")
            cwd = os.getcwd()
            os.chdir(sub)
            try:
                from gdevdocs_core.environment import get_output_dir

                self.assertEqual(get_output_dir(), root / "temp" / "gdevdocs_mcp")
            finally:
                os.chdir(cwd)
                if saved is None:
                    os.environ.pop(OUTPUT_DIR_ENV, None)
                else:
                    os.environ[OUTPUT_DIR_ENV] = saved
                if home is None:
                    os.environ.pop(CONFIG_HOME_ENV, None)
                else:
                    os.environ[CONFIG_HOME_ENV] = home

    def test_project_api_key_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / ".gdevdocs.toml").write_text('api_key = "secret"\n', encoding="utf-8")
            home = os.environ.get(CONFIG_HOME_ENV)
            os.environ[CONFIG_HOME_ENV] = str(root / "no-config")
            cwd = os.getcwd()
            os.chdir(root)
            try:
                with self.assertRaises(ConfigError):
                    load_config_files()
            finally:
                os.chdir(cwd)
                if home is None:
                    os.environ.pop(CONFIG_HOME_ENV, None)
                else:
                    os.environ[CONFIG_HOME_ENV] = home


class CliTests(unittest.TestCase):
    def test_version_is_one_stdout_line(self) -> None:
        out, err = StringIO(), StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err):
            with self.assertRaises(SystemExit) as caught:
                main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        manifest = tomllib.loads((SRC / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(out.getvalue(), f"gdevdocs {manifest['project']['version']}\n")
        self.assertEqual(err.getvalue(), "")

    def test_missing_key_exits_1_without_connecting(self) -> None:
        called = False

        def fake(*_args, **_kwargs):
            nonlocal called
            called = True
            raise AssertionError("must not connect")

        with TemporaryDirectory() as tmp:
            with _isolated_env(tmp):
                out, err = StringIO(), StringIO()
                with patch("gdevdocs_cli.client.call_tool", fake):
                    with patch("sys.stdout", out), patch("sys.stderr", err):
                        code = main(["search", "cloud storage bucket"])
        self.assertFalse(called)
        self.assertEqual(code, EXIT_RUNTIME_ERROR)
        message = err.getvalue()
        self.assertIn(API_KEY_ENV, message)
        self.assertIn("未設定", message)
        self.assertIn("developerknowledge.googleapis.com", message)
        self.assertIn("README", message)
        self.assertEqual(out.getvalue(), "")

    def test_empty_search_exits_4(self) -> None:
        def fake(*_args, **_kwargs):
            return _result(structured={"results": []})

        with TemporaryDirectory() as tmp:
            with _isolated_env(tmp, **{API_KEY_ENV: "test-key"}):
                err = StringIO()
                with patch("gdevdocs_cli.client.call_tool", fake):
                    with patch("sys.stderr", err):
                        code = main(["search", "nothing-matches"])
                self.assertEqual(code, EXIT_EMPTY_RESULT)
                self.assertEqual(list(Path(tmp).glob("*/index.md")), [])

    def test_search_prints_only_the_index_path(self) -> None:
        def fake(endpoint, api_key, timeout, tool_name, arguments, *, retry_rate_limit):
            self.assertEqual(tool_name, "search_documents")
            self.assertEqual(arguments, {"query": "create a bucket"})
            self.assertTrue(retry_rate_limit)
            self.assertEqual(api_key, "test-key")
            return _result(
                structured={
                    "results": [{"parent": PARENT, "id": "c1", "content": "Create a bucket."}]
                }
            )

        with TemporaryDirectory() as tmp:
            with _isolated_env(tmp, **{API_KEY_ENV: "test-key"}):
                out = StringIO()
                with patch("gdevdocs_cli.client.call_tool", fake):
                    with patch("sys.stdout", out):
                        code = main(["search", "create a bucket"])
                self.assertEqual(code, EXIT_SUCCESS)
                index = Path(out.getvalue().strip())
                self.assertEqual(index.name, "index.md")
                self.assertIn(
                    f"URL: {PAGE_URL}", (index.parent / "0001.md").read_text(encoding="utf-8")
                )

    def test_tool_error_exits_3(self) -> None:
        def fake(*_args, **_kwargs):
            return _result(is_error=True, text="documents/missing was rejected")

        with TemporaryDirectory() as tmp:
            with _isolated_env(tmp, **{API_KEY_ENV: "test-key"}):
                with patch("gdevdocs_cli.client.call_tool", fake):
                    code = main(["fetch", PARENT])
        self.assertEqual(code, EXIT_TOOL_ERROR)

    def test_answer_does_not_retry_rate_limits(self) -> None:
        seen = {}

        def fake(*_args, **kwargs):
            seen.update(kwargs)
            return _result(
                structured={"answerText": "A bucket holds objects.", "references": [PARENT]}
            )

        with TemporaryDirectory() as tmp:
            with _isolated_env(tmp, **{API_KEY_ENV: "test-key"}):
                with patch("gdevdocs_cli.client.call_tool", fake):
                    code = main(["answer", "what is a bucket"])
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertFalse(seen["retry_rate_limit"])
        self.assertFalse(retries_rate_limit("answer_query"))
        self.assertTrue(retries_rate_limit("search_documents"))
        self.assertTrue(retries_rate_limit("get_documents"))

    def test_too_many_fetch_names_exit_2(self) -> None:
        names = [f"documents/example.com/page-{i}" for i in range(21)]
        with TemporaryDirectory() as tmp:
            with _isolated_env(tmp, **{API_KEY_ENV: "test-key"}):
                with self.assertRaises(SystemExit) as caught:
                    main(["fetch", *names])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
