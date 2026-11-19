"""Direct HTML title fetching, shared by the wrapper scripts.

This module owns the *local* (non-Tavily) way to resolve a page title: fetch the
URL over plain HTTP, parse ``<title>`` / ``og:title`` / ``twitter:title`` out of
the document, and fall back to a slug built from the URL when that fails. Tavily
is never used for titles (an explicit project requirement) — only this code is.

Two consumers share it:
  * ``map_site_titles.py`` resolves a title for every mapped URL.
  * ``topic_layout.py`` back-fills a ``title`` for content-series results whose
    items arrive without one (notably ``crawl``'s ``CrawlResultItem``, which is
    ``url`` + ``raw_content`` only) before splitting them into per-URL files.

Edit the fetch defaults (user agent, timeout, byte cap, worker count) in the
constants below. ``PageTitleResult`` mirrors the ``SitePageItem`` TypedDict in
``tavily_types.py``; keep the two in sync.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; tavily-map-site-titles/1.0)"
DEFAULT_ACCEPT_HEADER = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"
TITLE_FALLBACK_LABEL = "Untitled"
TITLE_SEPARATOR_PATTERN = re.compile(r"\s*[|\-:–—]\s*")

# Shared default fetch budget. ``map_site_titles`` still overrides these per
# ``--detail`` preset; ``topic_layout``'s title back-fill uses these as-is.
DEFAULT_TITLE_OPTIONS: dict[str, Any] = {
    "max_workers": 6,
    "timeout_seconds": 12.0,
    "max_bytes": 196608,
}


class TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._title_chunks: list[str] = []
        self.og_title: str | None = None
        self.twitter_title: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True
            return

        if tag.lower() != "meta":
            return

        attributes = {name.lower(): (value or "") for name, value in attrs}
        property_name = attributes.get("property", "").lower()
        meta_name = attributes.get("name", "").lower()
        content = clean_text(attributes.get("content", ""))
        if not content:
            return
        if property_name == "og:title" and not self.og_title:
            self.og_title = content
        if meta_name == "twitter:title" and not self.twitter_title:
            self.twitter_title = content

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_chunks.append(data)

    @property
    def title(self) -> str | None:
        value = clean_text(" ".join(self._title_chunks))
        return value or None


@dataclass(slots=True)
class PageTitleResult:
    url: str
    title: str
    short_title: str | None
    title_source: str
    final_url: str | None
    content_type: str | None
    status_code: int | None
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "short_title": self.short_title,
            "title_source": self.title_source,
            "final_url": self.final_url,
            "content_type": self.content_type,
            "status_code": self.status_code,
            "error": self.error,
        }


def clean_text(value: str) -> str:
    return " ".join(unescape(value).split())


def shorten_title(title: str) -> str | None:
    parts = [clean_text(part) for part in TITLE_SEPARATOR_PATTERN.split(title) if clean_text(part)]
    if len(parts) <= 1:
        return None
    preferred = parts[0]
    return preferred if preferred != title else None


def build_title_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = PurePosixPath(parsed.path or "/")
    if path.name:
        raw_segment = path.name
    elif len(path.parts) > 1:
        raw_segment = path.parts[-1]
    else:
        raw_segment = parsed.netloc or TITLE_FALLBACK_LABEL
    label = raw_segment.replace("-", " ").replace("_", " ").strip()
    return clean_text(label.title()) or parsed.netloc or TITLE_FALLBACK_LABEL


def fetch_page_title(url: str, *, timeout_seconds: float, max_bytes: int) -> PageTitleResult:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": DEFAULT_ACCEPT_HEADER,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status_code = getattr(response, "status", None)
            final_url = response.geturl()
            headers = response.headers
            content_type = headers.get("Content-Type")
            charset = (
                headers.get_content_charset() if hasattr(headers, "get_content_charset") else None
            )
            body = response.read(max_bytes)
    except Exception as exc:
        fallback = build_title_from_url(url)
        return PageTitleResult(
            url=url,
            title=fallback,
            short_title=None,
            title_source="url_fallback",
            final_url=None,
            content_type=None,
            status_code=None,
            error=str(exc),
        )

    parsed_content_type = (content_type or "").lower()
    if "html" not in parsed_content_type and "xml" not in parsed_content_type:
        fallback = build_title_from_url(final_url or url)
        return PageTitleResult(
            url=url,
            title=fallback,
            short_title=None,
            title_source="url_fallback",
            final_url=final_url,
            content_type=content_type,
            status_code=status_code,
            error=f"Unsupported content type for title parsing: {content_type}",
        )

    encoding = charset or "utf-8"
    html = body.decode(encoding, errors="replace")
    parser = TitleParser()
    parser.feed(html)

    title = parser.og_title or parser.twitter_title or parser.title
    if title:
        return PageTitleResult(
            url=url,
            title=title,
            short_title=shorten_title(title),
            title_source="html",
            final_url=final_url,
            content_type=content_type,
            status_code=status_code,
            error=None,
        )

    fallback = build_title_from_url(final_url or url)
    return PageTitleResult(
        url=url,
        title=fallback,
        short_title=None,
        title_source="url_fallback",
        final_url=final_url,
        content_type=content_type,
        status_code=status_code,
        error="No title metadata found in the fetched document.",
    )


def collect_titles(
    urls: Sequence[str], *, title_options: Mapping[str, Any]
) -> list[dict[str, Any]]:
    normalized_urls = [url.strip() for url in urls if url and url.strip()]
    # Preserve first-seen order while deduping.
    seen: set[str] = set()
    deduped: list[str] = []
    for url in normalized_urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    if not deduped:
        return []

    max_workers = min(title_options["max_workers"], len(deduped))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(
            executor.map(
                lambda current_url: fetch_page_title(
                    current_url,
                    timeout_seconds=title_options["timeout_seconds"],
                    max_bytes=title_options["max_bytes"],
                ),
                deduped,
            )
        )
    return [result.as_dict() for result in results]
