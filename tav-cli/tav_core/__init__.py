"""Shared core for the ``tav`` Tavily wrapper scripts.

This package holds everything the wrapper scripts (``search_topic`` etc.) and
``tav_cli`` build on, split by responsibility so no single file grows unwieldy:

  * ``result_contract`` — the return contract: ``ExitCode`` / ``ResultKind`` /
    ``OutputChannel`` / the envelopes / ``RunOutcome`` / role-layout tables.
  * ``tavily_types``    — empirically-pinned shapes of Tavily's per-item responses.
  * ``environment``     — ``.env`` loading, the Tavily client, env toggles.
  * ``page_title``      — direct HTML title fetching (never via Tavily).
  * ``text_utils``      — ``slugify`` / ``dedupe_preserve_order``.
  * ``projection``      — shape result items down to research-relevant keys.
  * ``output``          — the single ``emit()`` sink + serialization + builders.
  * ``topic_layout``    — the role-based ``--topic`` writers (what goes where).
  * ``run_shell``       — the imperative shell ``finalize()`` + detached spawning.

Import the public surface straight from the package (``from tav_core import
ExitCode, finalize, ...``); the names below are re-exported so callers do not
depend on the internal file layout. Submodules stay importable for the few
places that need to reach a specific one (e.g. tests patching
``tav_core.topic_layout.fetch_page_title`` or ``tav_core.output.LOG_DIRECTORY``).
"""

from __future__ import annotations

from tav_core.environment import (
    create_tavily_client,
    get_missing_api_key_message,
    get_normalized_api_key,
    get_output_dir,
    load_environment,
    should_show_log_path,
    should_write_log,
)
from tav_core.output import (
    build_log_output_path,
    build_response_payload,
    build_result_envelope,
    emit,
    render_json,
    write_output,
)
from tav_core.page_title import (
    DEFAULT_TITLE_OPTIONS,
    PageTitleResult,
    build_title_from_url,
    collect_titles,
    fetch_page_title,
)
from tav_core.result_contract import (
    PROJECTION_KEYS,
    ROLE_CONTENT,
    ROLE_DISCOVERY,
    ROLE_FOR_KIND,
    ROLE_REPORT,
    SUBDIR_FOR_KIND,
    TOPIC_ARG_HELP,
    BackgroundTask,
    EnvironmentInfo,
    ExitCode,
    OutputChannel,
    ResponseEnvelope,
    ResultEnvelope,
    ResultKind,
    RunOutcome,
    TopicArtifact,
    role_for,
)
from tav_core.tavily_types import (
    CompletedResearchResponse,
    CrawlResultItem,
    ExtractFailedItem,
    ExtractResultItem,
    ResearchSource,
    SearchResultItem,
    SitePageItem,
)
from tav_core.projection import project_result, slim_result_item
from tav_core.run_shell import finalize, spawn_detached
from tav_core.text_utils import dedupe_preserve_order, slugify
from tav_core.topic_layout import (
    emit_payload,
    ensure_item_titles,
    load_pages_index,
    next_sequence,
    render_page_markdown,
    resolve_output_target,
    write_topic_artifact,
)

__all__ = [
    # result_contract
    "PROJECTION_KEYS",
    "ROLE_CONTENT",
    "ROLE_DISCOVERY",
    "ROLE_FOR_KIND",
    "ROLE_REPORT",
    "SUBDIR_FOR_KIND",
    "TOPIC_ARG_HELP",
    "BackgroundTask",
    "EnvironmentInfo",
    "ExitCode",
    "OutputChannel",
    "ResponseEnvelope",
    "ResultEnvelope",
    "ResultKind",
    "RunOutcome",
    "TopicArtifact",
    "role_for",
    # tavily_types
    "CompletedResearchResponse",
    "CrawlResultItem",
    "ExtractFailedItem",
    "ExtractResultItem",
    "ResearchSource",
    "SearchResultItem",
    "SitePageItem",
    # environment
    "create_tavily_client",
    "get_missing_api_key_message",
    "get_normalized_api_key",
    "get_output_dir",
    "load_environment",
    "should_show_log_path",
    "should_write_log",
    # page_title
    "DEFAULT_TITLE_OPTIONS",
    "PageTitleResult",
    "build_title_from_url",
    "collect_titles",
    "fetch_page_title",
    # text_utils
    "dedupe_preserve_order",
    "slugify",
    # output
    "build_log_output_path",
    "build_response_payload",
    "build_result_envelope",
    "emit",
    "render_json",
    "write_output",
    # topic_layout
    "emit_payload",
    "ensure_item_titles",
    "finalize",
    "load_pages_index",
    "next_sequence",
    "project_result",
    "render_page_markdown",
    "resolve_output_target",
    "slim_result_item",
    "spawn_detached",
    "write_topic_artifact",
]
