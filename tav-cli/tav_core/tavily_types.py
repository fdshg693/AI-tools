"""Tavily per-item result types — EMPIRICALLY pinned, not copied from the docs.

Each TypedDict here names the concrete shape of one object inside the ``result``
list that ``result_contract.ResultKind`` discriminates, as observed from the LIVE
Tavily API (tavily-python 0.7.x) when called with THIS skill's fixed wrapper flags
(``include_raw_content`` / ``include_images`` / ``include_favicon`` all False,
``format="markdown"``). They are deliberately narrower than "some dict":
downstream code may rely on every key declared here. Real captured responses live
in ``tests/fixtures/`` and ``tests/test_result_types.py`` keeps these definitions
honest against them.

Where the published reference disagreed with reality, reality wins (verified
against live responses on 2026-06-10):
  - search items ALWAYS carry a ``raw_content`` key — value ``None`` under our
    flags (the docs imply the key only appears with ``include_raw_content``).
  - extract items carry an UNDOCUMENTED ``title``; ``images`` is a (usually
    empty) list even with ``include_images=False``.
  - crawl items carry ONLY ``url`` + ``raw_content`` (nullable) under our flags
    — no ``title`` / ``images`` / ``favicon``.
  - a completed research response's ``sources[]`` are ``{url, title, favicon}``
    (the docs said ``{url, title, citation}``).
"""

from __future__ import annotations

from typing import TypedDict


class SearchResultItem(TypedDict):
    """One object in ``search_topic.py`` results (``ResultKind.SEARCH_RESULTS``)."""

    title: str
    url: str
    content: str  # NLP summary or reranked chunks, depending on search_depth
    score: float  # semantic relevance, 0-1
    raw_content: str | None  # None under our flags; str only if include_raw_content is enabled


class ExtractResultItem(TypedDict):
    """One object in extract results (``ResultKind.EXTRACT_RESULTS``).

    Shared by ``extract_url_content`` / ``search_extract_topic`` /
    ``map_extract_site_content`` (they all emit Tavily extract objects).
    """

    url: str
    title: str  # present in practice, though absent from the published Response Fields
    raw_content: str  # full page content, or query-reranked chunks joined by " [...] "
    images: list[str]  # empty list under our flags (include_images=False)


class ExtractFailedItem(TypedDict):
    """One object in an extract response's ``failed_results``.

    Failures are surfaced as a non-success ``ExitCode`` and the details are
    discarded downstream, so this is typed only lightly.
    """

    url: str
    error: str


class CrawlResultItem(TypedDict):
    """One object in ``crawl_site_content.py`` results (``ResultKind.CRAWL_RESULTS``)."""

    url: str
    raw_content: str | None  # None when the crawled page yielded no extractable content


class SitePageItem(TypedDict):
    """One object in ``map_site_titles.py`` results (``ResultKind.SITE_PAGES``).

    Built locally from ``page_title.PageTitleResult.as_dict()`` (NOT a raw Tavily
    object), so this shape is fully under our control. The underlying ``map``
    call's own ``results`` is a ``list[str]`` of URLs, consumed internally to
    produce these records. Mirror this with ``page_title.PageTitleResult``.
    """

    url: str
    title: str
    short_title: str | None
    title_source: str  # "html" | "url_fallback"
    final_url: str | None
    content_type: str | None
    status_code: int | None
    error: str | None


class ResearchSource(TypedDict):
    """One object in a completed research response's ``sources`` list."""

    url: str
    title: str
    favicon: str


class CompletedResearchResponse(TypedDict):
    """Shape of a COMPLETED ``get_research`` response.

    ``research_topic.py`` emits ``content`` (a ``str``) as its
    ``RESEARCH_REPORT`` result on success, falling back to this whole dict on a
    non-completed terminal status. ``status`` is ``"completed"`` here.
    """

    status: str
    content: str
    sources: list[ResearchSource]
    created_at: str
    response_time: float
    request_id: str
