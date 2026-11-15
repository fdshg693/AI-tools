"""Turn one raw MCP result item into a (category, title, markdown) triple for
`output.write_query_results`.

Each `render_*_item` here owns the on-disk shape for its tool's results; `output.py`
only knows how to write a (category, title, content) triple into a query folder --
it has no idea what a search hit or a code sample looks like. `category` is ``""``
for official docs (written at the folder root) or ``"qa"`` for Microsoft Q&A
community answers (written under a `qa/` subfolder so they don't mix with
first-party docs in the same listing).
"""

from __future__ import annotations

import re
from typing import Any

_MARKDOWN_TITLE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_URL_LINE = re.compile(r"^URL:\s+\S+", re.MULTILINE)
_QA_URL_MARKER = "learn.microsoft.com/answers/"
_URL_LINE_SCAN_LINES = 15


def _clean_title(text: str) -> str:
    """Collapse embedded newlines/whitespace runs so a title is always one line.

    The MCP server's `microsoft_code_sample_search` occasionally returns a
    `description` with metadata (e.g. "language: python") appended after an
    embedded newline -- left as-is, that breaks both the `# ` heading in the
    written file and the index.md listing.
    """
    return " ".join(text.split())


def _is_qa_url(url: str) -> bool:
    """Microsoft Q&A community answers live under .../answers/ on the same domain

    as official docs, but the `microsoft_docs_search` tool doesn't separate them
    from first-party content -- so results are classified from the URL shape.
    """
    return _QA_URL_MARKER in url


def render_search_item(item: dict[str, Any]) -> tuple[str, str, str]:
    title = _clean_title(item.get("title") or "(untitled)")
    url = item.get("contentUrl", "")
    content = f"# {title}\n\nURL: {url}\n\n{item.get('content', '')}"
    category = "qa" if _is_qa_url(url) else ""
    return category, title, content


def render_code_item(item: dict[str, Any]) -> tuple[str, str, str]:
    title = _clean_title(item.get("description") or "(no description)")
    language = item.get("language", "")
    content = (
        f"# {title}\n\n"
        f"Language: {language}\n"
        f"Link: {item.get('link', '')}\n\n"
        f"```{language}\n{item.get('codeSnippet', '')}\n```"
    )
    return "", title, content


def _with_source_url(markdown: str, url: str) -> str:
    """Insert `URL: <url>` after the leading H1 so fetch files match search files.

    `aim --parallel` prompts in the `ms-digest` skill look for a `URL:` line near the
    top. Search results already had one; fetch used to write the MCP markdown
    unchanged, so digesting a fetch folder dropped the source URL.
    """
    head = "\n".join(markdown.splitlines()[:_URL_LINE_SCAN_LINES])
    if _URL_LINE.search(head):
        return markdown
    url_line = f"URL: {url}"
    heading_match = _MARKDOWN_TITLE.search(markdown)
    if heading_match is None:
        return f"{url_line}\n\n{markdown}"
    before = markdown[: heading_match.end()]
    after = markdown[heading_match.end() :].lstrip("\n")
    return f"{before}\n\n{url_line}\n\n{after}"


def render_fetch_item(url: str, markdown: str) -> tuple[str, str, str]:
    title_match = _MARKDOWN_TITLE.search(markdown)
    raw_title = title_match.group(1) if title_match else url.rstrip("/").rsplit("/", 1)[-1]
    return "", _clean_title(raw_title), _with_source_url(markdown, url)
