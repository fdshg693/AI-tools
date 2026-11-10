r"""Offline tests for the role-based ``--topic`` output layout (no network, no credits).

These cover the role-based output layout in ``tav_core`` (``topic_layout`` /
``page_title``) — output is filed by the *role* of its ``result_kind`` so kinds
never mix:

  * helpers: ``role_for`` / ``slugify`` / ``next_sequence`` / ``render_page_markdown`` /
    ``slim_result_item`` / ``should_write_log`` / ``should_show_log_path`` /
    ``resolve_output_target``.
  * role separation: search -> ``search/``, map -> ``map/``, extract/crawl ->
    ``pages/``, research -> ``research/`` — never mixed in one series.
  * discovery aggregation: search/map write ONE list file (not split per-URL),
    projected to the triage columns, named ``NNNN-<slug>.json``.
  * content split + md: extract/crawl write one ``NNNN-<slug>.md`` per page
    (``# title`` + body) plus an appended ``pages/index.json``, each entry
    carrying ``char_count`` (= ``len()`` of the written ``.md``).
  * append / duplicate-keep: re-running the same topic continues ``NNNN`` and
    keeps duplicates (same URL extracted twice -> two pages + two index entries).
  * projection: search rows drop ``raw_content``; extract pages carry no images;
    the audit log keeps the raw fields.
  * report: research success -> one ``.md``; failure -> one ``.json``.
  * log-path-notice toggle: ``TAVILY_SHOW_LOG_PATH=false`` silences the
    "Wrote full log …" line but result-file path notices are always shown.
  * log toggle: ``TAVILY_WRITE_LOG=false`` writes no ``logs/<script>-log.json``.
  * stdout contract: no ``--topic`` -> a single (projected) ``ResultEnvelope``.

Run (stdlib only):
    python -m unittest discover -s tools/tav-cli/tests
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent
sys.path.insert(0, str(SRC))

import tav_core as tc  # noqa: E402
import tav_core.environment as env  # noqa: E402
from tav_core import (  # noqa: E402
    ExitCode,
    PageTitleResult,
    ResultKind,
    TopicArtifact,
    build_title_from_url,
    emit_payload,
    next_sequence,
    render_page_markdown,
    resolve_output_target,
    role_for,
    should_show_log_path,
    should_write_log,
    slim_result_item,
    slugify,
)


def make_log(script: str) -> dict:
    return {
        "script": script,
        "request": {},
        "environment": {"config_files": [], "setting_sources": {}, "api_key_present": False},
        "response": {},
    }


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def stub_title(url, *, timeout_seconds, max_bytes):
    """Offline stand-in for the HTML title fetch (keeps the suite network-free)."""
    return PageTitleResult(
        url=url,
        title=f"Title for {url}",
        short_title=None,
        title_source="html",
        final_url=url,
        content_type="text/html",
        status_code=200,
        error=None,
    )


class EnvGuard(unittest.TestCase):
    """Snapshot/restore the env vars these tests mutate, and point the global
    config at an empty temp dir so the developer's real config never leaks in."""

    _KEYS = (
        "TAVILY_API_KEY",
        "TAVILY_OUTPUT_DIR",
        "TAVILY_WRITE_LOG",
        "TAVILY_SHOW_LOG_PATH",
        "TAVILY_LOG_DIR",
        "TAV_CONFIG_HOME",
    )

    def setUp(self) -> None:
        self._saved = {k: os.environ.get(k) for k in self._KEYS}
        self._config_home = TemporaryDirectory()
        self.addCleanup(self._config_home.cleanup)
        os.environ["TAV_CONFIG_HOME"] = self._config_home.name

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestHelpers(EnvGuard):
    def test_role_for(self) -> None:
        self.assertEqual(role_for(ResultKind.SEARCH_RESULTS), tc.ROLE_DISCOVERY)
        self.assertEqual(role_for(ResultKind.SITE_PAGES), tc.ROLE_DISCOVERY)
        self.assertEqual(role_for(ResultKind.EXTRACT_RESULTS), tc.ROLE_CONTENT)
        self.assertEqual(role_for(ResultKind.CRAWL_RESULTS), tc.ROLE_CONTENT)
        self.assertEqual(role_for(ResultKind.RESEARCH_REPORT), tc.ROLE_REPORT)

    def test_subdir_for_kind(self) -> None:
        self.assertEqual(tc.SUBDIR_FOR_KIND[ResultKind.SEARCH_RESULTS], "search")
        self.assertEqual(tc.SUBDIR_FOR_KIND[ResultKind.SITE_PAGES], "map")
        self.assertEqual(tc.SUBDIR_FOR_KIND[ResultKind.EXTRACT_RESULTS], "pages")
        self.assertEqual(tc.SUBDIR_FOR_KIND[ResultKind.CRAWL_RESULTS], "pages")
        self.assertEqual(tc.SUBDIR_FOR_KIND[ResultKind.RESEARCH_REPORT], "research")

    def test_slugify(self) -> None:
        self.assertEqual(slugify("Fabric vs Synapse"), "fabric-vs-synapse")
        self.assertEqual(slugify("learn.microsoft.com"), "learn-microsoft-com")
        self.assertEqual(slugify("  multiple   --- spaces  "), "multiple-spaces")
        self.assertEqual(slugify(""), "item")
        self.assertEqual(slugify(None), "item")
        # Unicode word characters (e.g. Japanese) survive verbatim.
        self.assertEqual(slugify("東京 タワー"), "東京-タワー")
        # Long input is truncated and never ends on a hyphen.
        long_slug = slugify("a" * 80)
        self.assertLessEqual(len(long_slug), 50)
        self.assertFalse(long_slug.endswith("-"))

    def test_next_sequence(self) -> None:
        with TemporaryDirectory() as tmp:
            d = Path(tmp) / "search"
            self.assertEqual(next_sequence(d), 1)  # missing dir
            d.mkdir(parents=True)
            self.assertEqual(next_sequence(d), 1)  # empty dir
            (d / "0001-foo.json").write_text("{}", encoding="utf-8")
            (d / "0004-bar.json").write_text("{}", encoding="utf-8")
            (d / "index.json").write_text("{}", encoding="utf-8")  # ignored (no NNNN prefix)
            self.assertEqual(next_sequence(d), 5)

    def test_render_page_markdown(self) -> None:
        self.assertEqual(render_page_markdown("Title", "body"), "# Title\n\nbody\n")
        self.assertEqual(render_page_markdown("Only title", ""), "# Only title\n")
        self.assertEqual(render_page_markdown(None, "x"), "# Untitled\n\nx\n")

    def test_slim_result_item(self) -> None:
        search = {"url": "u", "title": "t", "content": "c", "score": 0.5, "raw_content": None}
        self.assertEqual(
            slim_result_item(ResultKind.SEARCH_RESULTS, search),
            {"url": "u", "title": "t", "content": "c", "score": 0.5},
        )
        extract = {"url": "u", "title": "t", "raw_content": "body", "images": []}
        self.assertEqual(
            slim_result_item(ResultKind.EXTRACT_RESULTS, extract),
            {"url": "u", "title": "t", "raw_content": "body"},
        )
        # research_report has no projection: returned unchanged.
        self.assertEqual(slim_result_item(ResultKind.RESEARCH_REPORT, "# Report"), "# Report")

    def test_resolve_output_target_uses_env(self) -> None:
        os.environ["TAVILY_OUTPUT_DIR"] = "some/base"
        base = env.find_git_root() or Path.cwd()
        self.assertEqual(resolve_output_target("topicx"), base / "some/base" / "topicx")

    def test_resolve_output_target_defaults_to_temp_web(self) -> None:
        os.environ.pop("TAVILY_OUTPUT_DIR", None)
        base = env.find_git_root() or Path.cwd()
        self.assertEqual(resolve_output_target("t"), base / "temp/web" / "t")

    def test_resolve_output_target_flattens_traversal(self) -> None:
        target = resolve_output_target("../../etc", output_dir=Path("base"))
        self.assertEqual(target.parent, Path("base"))
        self.assertNotIn("..", target.name.split(os.sep))

    def test_should_write_log_default_true(self) -> None:
        os.environ.pop("TAVILY_WRITE_LOG", None)
        self.assertTrue(should_write_log())

    def test_should_write_log_falsey_values(self) -> None:
        for value in ("false", "FALSE", "0", "no", "off", ""):
            os.environ["TAVILY_WRITE_LOG"] = value
            self.assertFalse(should_write_log(), f"{value!r} should suppress the log")
        for value in ("true", "1", "yes"):
            os.environ["TAVILY_WRITE_LOG"] = value
            self.assertTrue(should_write_log(), f"{value!r} should enable the log")

    def test_should_show_log_path_default_true(self) -> None:
        os.environ.pop("TAVILY_SHOW_LOG_PATH", None)
        self.assertTrue(should_show_log_path())

    def test_should_show_log_path_falsey(self) -> None:
        for value in ("false", "0", "no", "off", ""):
            os.environ["TAVILY_SHOW_LOG_PATH"] = value
            self.assertFalse(
                should_show_log_path(), f"{value!r} should silence the log-path notice"
            )


class TestLayoutWriters(EnvGuard):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = TemporaryDirectory()
        self.base = Path(self._tmp.name)
        os.environ["TAVILY_OUTPUT_DIR"] = str(self.base)
        os.environ["TAVILY_WRITE_LOG"] = "false"  # keep logs clean in tests

    def tearDown(self) -> None:
        self._tmp.cleanup()
        super().tearDown()

    def _emit(self, **kwargs) -> None:
        with redirect_stderr(io.StringIO()):
            emit_payload(**kwargs)

    # -- discovery aggregation --------------------------------------------
    def test_search_discovery_is_one_aggregated_list_file(self) -> None:
        results = [
            {"title": "A", "url": "https://a", "content": "c", "score": 0.5, "raw_content": None},
            {"title": "B", "url": "https://b", "content": "c2", "score": 0.4, "raw_content": None},
        ]
        self._emit(
            payload=make_log("search_topic.py"),
            topic="topic_s",
            result_kind=ResultKind.SEARCH_RESULTS,
            result=results,
            exit_code=ExitCode.SUCCESS,
            slug="microsoft fabric overview",
        )
        search_dir = self.base / "topic_s" / "search"
        files = sorted(p.name for p in search_dir.glob("*.json"))
        self.assertEqual(files, ["0001-microsoft-fabric-overview.json"])
        envelope = read_json(search_dir / files[0])
        self.assertEqual(envelope["result_kind"], "search_results")
        # All rows in ONE file (not split per-URL), and projected (no raw_content).
        self.assertEqual([r["url"] for r in envelope["result"]], ["https://a", "https://b"])
        for row in envelope["result"]:
            self.assertNotIn("raw_content", row)
        # No other role folders created.
        self.assertFalse((self.base / "topic_s" / "pages").exists())
        self.assertFalse((self.base / "topic_s" / "research").exists())

    def test_map_discovery_subfolder_and_slug(self) -> None:
        self._emit(
            payload=make_log("map_site_titles.py"),
            topic="topic_m",
            result_kind=ResultKind.SITE_PAGES,
            result=[
                {"url": "https://a", "title": "A", "short_title": None, "title_source": "html"}
            ],
            exit_code=ExitCode.SUCCESS,
            slug="learn.microsoft.com",
        )
        f = self.base / "topic_m" / "map" / "0001-learn-microsoft-com.json"
        self.assertTrue(f.exists())
        row = read_json(f)["result"][0]
        self.assertEqual(set(row), {"url", "title", "short_title"})  # projected, no title_source

    # -- content split + markdown -----------------------------------------
    def test_content_writes_md_per_page_plus_index(self) -> None:
        # Crawl items carry no title; stub the fetch so the suite stays offline.
        original = tc.topic_layout.fetch_page_title
        tc.topic_layout.fetch_page_title = stub_title
        try:
            results = [
                {"url": "https://x/1", "raw_content": "one"},
                {"url": "https://x/2", "raw_content": "two"},
            ]
            self._emit(
                payload=make_log("crawl_site_content.py"),
                topic="topic_c",
                result_kind=ResultKind.CRAWL_RESULTS,
                result=results,
                exit_code=ExitCode.SUCCESS,
            )
        finally:
            tc.topic_layout.fetch_page_title = original

        pages = self.base / "topic_c" / "pages"
        md_files = sorted(p.name for p in pages.glob("*.md"))
        self.assertEqual(len(md_files), 2)
        index = read_json(pages / "index.json")
        self.assertEqual(index["topic"], "topic_c")
        self.assertEqual(len(index["entries"]), 2)
        for entry in index["entries"]:
            md = (pages / entry["file"]).read_text(encoding="utf-8")
            self.assertTrue(md.startswith("# "))  # H1 title header
            self.assertEqual(entry["result_kind"], "crawl_results")
            self.assertEqual(entry["script"], "crawl_site_content.py")
            self.assertTrue(entry["title"])
            self.assertEqual(entry["char_count"], len(md))

    def test_content_keeps_existing_title_without_fetch(self) -> None:
        def must_not_call(url, *, timeout_seconds, max_bytes):  # pragma: no cover
            raise AssertionError("fetch_page_title must not be called when titles exist")

        original = tc.topic_layout.fetch_page_title
        tc.topic_layout.fetch_page_title = must_not_call
        try:
            self._emit(
                payload=make_log("extract_url_content.py"),
                topic="topic_e",
                result_kind=ResultKind.EXTRACT_RESULTS,
                result=[
                    {"url": "https://a", "title": "Kept Title", "raw_content": "x", "images": []}
                ],
                exit_code=ExitCode.SUCCESS,
            )
        finally:
            tc.topic_layout.fetch_page_title = original

        index = read_json(self.base / "topic_e" / "pages" / "index.json")
        entry = index["entries"][0]
        self.assertEqual(entry["title"], "Kept Title")
        self.assertEqual(entry["title_source"], "existing")
        self.assertEqual(entry["file"], "0001-kept-title.md")
        md = (self.base / "topic_e" / "pages" / entry["file"]).read_text(encoding="utf-8")
        self.assertIn("# Kept Title", md)
        self.assertIn("x", md)  # body present, no images key leaked

    def test_content_url_fallback_title(self) -> None:
        def failing(url, *, timeout_seconds, max_bytes):
            return PageTitleResult(
                url=url,
                title=build_title_from_url(url),
                short_title=None,
                title_source="url_fallback",
                final_url=None,
                content_type=None,
                status_code=None,
                error="boom",
            )

        original = tc.topic_layout.fetch_page_title
        tc.topic_layout.fetch_page_title = failing
        try:
            self._emit(
                payload=make_log("crawl_site_content.py"),
                topic="topic_fb",
                result_kind=ResultKind.CRAWL_RESULTS,
                result=[
                    {"url": "https://learn.microsoft.com/azure/fabric/overview", "raw_content": "x"}
                ],
                exit_code=ExitCode.SUCCESS,
            )
        finally:
            tc.topic_layout.fetch_page_title = original

        entry = read_json(self.base / "topic_fb" / "pages" / "index.json")["entries"][0]
        self.assertEqual(entry["title_source"], "url_fallback")
        self.assertEqual(entry["title"], "Overview")

    # -- append / duplicate-keep ------------------------------------------
    def test_discovery_appends_across_runs(self) -> None:
        for query in ("first query", "second query"):
            self._emit(
                payload=make_log("search_topic.py"),
                topic="topic_app",
                result_kind=ResultKind.SEARCH_RESULTS,
                result=[
                    {
                        "url": "https://a",
                        "title": "A",
                        "content": "c",
                        "score": 0.1,
                        "raw_content": None,
                    }
                ],
                exit_code=ExitCode.SUCCESS,
                slug=query,
            )
        files = sorted(p.name for p in (self.base / "topic_app" / "search").glob("*.json"))
        self.assertEqual(files, ["0001-first-query.json", "0002-second-query.json"])

    def test_content_appends_and_keeps_duplicates(self) -> None:
        original = tc.topic_layout.fetch_page_title
        tc.topic_layout.fetch_page_title = stub_title
        try:
            for _ in range(2):  # same URL extracted twice
                self._emit(
                    payload=make_log("extract_url_content.py"),
                    topic="topic_dup",
                    result_kind=ResultKind.EXTRACT_RESULTS,
                    result=[{"url": "https://x/same", "raw_content": "body", "images": []}],
                    exit_code=ExitCode.SUCCESS,
                )
        finally:
            tc.topic_layout.fetch_page_title = original

        pages = self.base / "topic_dup" / "pages"
        md_files = sorted(p.name for p in pages.glob("*.md"))
        self.assertEqual(len(md_files), 2)  # two files, duplicate kept
        self.assertTrue(md_files[0].startswith("0001-"))
        self.assertTrue(md_files[1].startswith("0002-"))
        index = read_json(pages / "index.json")
        self.assertEqual(len(index["entries"]), 2)  # two index entries, both the same URL
        self.assertEqual({e["url"] for e in index["entries"]}, {"https://x/same"})

    # -- composite: discovery + content both kept -------------------------
    def test_composite_keeps_both_search_menu_and_pages(self) -> None:
        original = tc.topic_layout.fetch_page_title
        tc.topic_layout.fetch_page_title = stub_title
        try:
            self._emit(
                payload=make_log("search_extract_topic.py"),
                topic="topic_se",
                result_kind=ResultKind.EXTRACT_RESULTS,
                result=[{"url": "https://x/1", "raw_content": "body", "images": []}],
                exit_code=ExitCode.SUCCESS,
                discovery=TopicArtifact(
                    result_kind=ResultKind.SEARCH_RESULTS,
                    result=[
                        {
                            "url": "https://x/1",
                            "title": "T",
                            "content": "c",
                            "score": 0.5,
                            "raw_content": None,
                        }
                    ],
                    slug="my query",
                ),
            )
        finally:
            tc.topic_layout.fetch_page_title = original

        # Discovery half -> search/, content half -> pages/.
        self.assertTrue((self.base / "topic_se" / "search" / "0001-my-query.json").exists())
        self.assertTrue((self.base / "topic_se" / "pages" / "index.json").exists())
        self.assertEqual(len(list((self.base / "topic_se" / "pages").glob("*.md"))), 1)

    # -- report -----------------------------------------------------------
    def test_research_success_writes_md(self) -> None:
        self._emit(
            payload=make_log("research_topic.py"),
            topic="topic_r",
            result_kind=ResultKind.RESEARCH_REPORT,
            result="# Report\n\nbody",
            exit_code=ExitCode.SUCCESS,
            slug="how does obo work",
        )
        f = self.base / "topic_r" / "research" / "0001-how-does-obo-work.md"
        self.assertTrue(f.exists())
        self.assertEqual(f.read_text(encoding="utf-8"), "# Report\n\nbody\n")

    def test_research_failure_writes_no_file(self) -> None:
        # "Report or nothing": a non-success outcome writes NO file into research/
        # (the audit log is the sole record; a foreground timeout is finished by a
        # detached poller instead). Earlier behavior wrote a .json failure stub.
        self._emit(
            payload=make_log("research_topic.py"),
            topic="topic_rf",
            result_kind=ResultKind.RESEARCH_REPORT,
            result={"status": "failed", "content": ""},
            exit_code=ExitCode.RUNTIME_ERROR,
            slug="bad question",
        )
        research_dir = self.base / "topic_rf" / "research"
        self.assertFalse((research_dir / "0001-bad-question.json").exists())
        self.assertEqual(list(research_dir.glob("*")) if research_dir.exists() else [], [])

    def test_research_incomplete_writes_no_file(self) -> None:
        # A foreground timeout (INCOMPLETE) likewise leaves research/ empty.
        self._emit(
            payload=make_log("research_topic.py"),
            topic="topic_ri",
            result_kind=ResultKind.RESEARCH_REPORT,
            result={"status": "in_progress"},
            exit_code=ExitCode.INCOMPLETE,
            slug="slow question",
        )
        research_dir = self.base / "topic_ri" / "research"
        self.assertEqual(list(research_dir.glob("*")) if research_dir.exists() else [], [])

    def test_empty_content_still_writes_index(self) -> None:
        self._emit(
            payload=make_log("search_extract_topic.py"),
            topic="topic_empty",
            result_kind=ResultKind.EXTRACT_RESULTS,
            result=[],
            exit_code=ExitCode.EMPTY_RESULT,
        )
        index = read_json(self.base / "topic_empty" / "pages" / "index.json")
        self.assertEqual(index["entries"], [])


class TestPathNoticeToggle(EnvGuard):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = TemporaryDirectory()
        self.base = Path(self._tmp.name)
        os.environ["TAVILY_OUTPUT_DIR"] = str(self.base)
        # A log must be written for the log-path notice to be in play.
        os.environ["TAVILY_WRITE_LOG"] = "true"
        self._orig_log_dir = tc.output.LOG_DIRECTORY
        tc.output.LOG_DIRECTORY = self.base / "logs"

    def tearDown(self) -> None:
        tc.output.LOG_DIRECTORY = self._orig_log_dir
        self._tmp.cleanup()
        super().tearDown()

    def _emit_capture_stderr(self) -> str:
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            emit_payload(
                make_log("search_topic.py"),
                topic="t",
                result_kind=ResultKind.SEARCH_RESULTS,
                result=[
                    {
                        "url": "https://a",
                        "title": "A",
                        "content": "c",
                        "score": 0.1,
                        "raw_content": None,
                    }
                ],
                exit_code=ExitCode.SUCCESS,
                slug="q",
            )
        return buffer.getvalue()

    def test_log_path_silenced_but_result_path_still_shown(self) -> None:
        os.environ["TAVILY_SHOW_LOG_PATH"] = "false"
        stderr = self._emit_capture_stderr()
        # The log-path notice is silenced ...
        self.assertNotIn("Wrote full log", stderr)
        # ... but the result-file path notice is always shown, and files exist.
        self.assertIn("Wrote 1 search_results row(s)", stderr)
        self.assertTrue((self.base / "t" / "search" / "0001-q.json").exists())

    def test_log_path_shown_by_default(self) -> None:
        os.environ.pop("TAVILY_SHOW_LOG_PATH", None)
        stderr = self._emit_capture_stderr()
        self.assertIn("Wrote full log", stderr)
        self.assertIn("Wrote 1 search_results row(s)", stderr)


class TestLogToggle(EnvGuard):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = TemporaryDirectory()
        self.base = Path(self._tmp.name)
        os.environ["TAVILY_OUTPUT_DIR"] = str(self.base)
        self._orig_log_dir = tc.output.LOG_DIRECTORY
        tc.output.LOG_DIRECTORY = self.base / "logs"

    def tearDown(self) -> None:
        tc.output.LOG_DIRECTORY = self._orig_log_dir
        self._tmp.cleanup()
        super().tearDown()

    def _emit(self) -> None:
        with redirect_stderr(io.StringIO()):
            emit_payload(
                make_log("search_topic.py"),
                topic="t",
                result_kind=ResultKind.SEARCH_RESULTS,
                result=[],
                exit_code=ExitCode.SUCCESS,
                slug="q",
            )

    def test_log_suppressed_when_false(self) -> None:
        os.environ["TAVILY_WRITE_LOG"] = "false"
        self._emit()
        self.assertFalse((self.base / "logs" / "search_topic-log.json").exists())

    def test_log_written_when_enabled(self) -> None:
        os.environ["TAVILY_WRITE_LOG"] = "true"
        self._emit()
        self.assertTrue((self.base / "logs" / "search_topic-log.json").exists())


class TestStdoutContract(EnvGuard):
    def test_no_topic_prints_single_projected_envelope(self) -> None:
        os.environ["TAVILY_WRITE_LOG"] = "false"
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            emit_payload(
                make_log("search_topic.py"),
                topic=None,
                result_kind=ResultKind.SEARCH_RESULTS,
                result=[
                    {
                        "title": "A",
                        "url": "https://a",
                        "content": "c",
                        "score": 0.1,
                        "raw_content": None,
                    }
                ],
                exit_code=ExitCode.SUCCESS,
            )
        envelope = json.loads(buffer.getvalue())
        self.assertEqual(envelope["result_kind"], "search_results")
        self.assertEqual(envelope["exit_code"], 0)
        self.assertEqual(envelope["result"][0]["url"], "https://a")
        # stdout is projected too: no raw_content noise.
        self.assertNotIn("raw_content", envelope["result"][0])


if __name__ == "__main__":
    unittest.main()
