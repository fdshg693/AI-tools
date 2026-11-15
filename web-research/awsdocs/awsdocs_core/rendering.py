"""Turn raw AWS Knowledge MCP result items into (category, title, markdown) triples
for `output.write_query_results`, plus the stdout tables for `regions` / `availability`.

Each `render_*` here owns the on-disk shape for its tool's results; `output.py`
only knows how to write a (category, title, content) triple into a query folder.
`category` is one of `output.CATEGORY_HEADINGS`: ``""`` for documentation
(folder root), ``"blog"`` / ``"whats-new"`` / ``"repost"`` for AWS Blog, What's
New and re:Post results, ``"skills"`` for AWS Agent Skill entries. The search
tool mixes all of these into one ranked list, so they are split by URL shape
(skill entries have no URL at all).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

_MARKDOWN_TITLE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_URL_LINE = re.compile(r"^URL:\s+\S+", re.MULTILINE)
_URL_LINE_SCAN_LINES = 15

_URL_CATEGORIES = (
    ("aws.amazon.com/blogs/", "blog"),
    ("aws.amazon.com/about-aws/whats-new/", "whats-new"),
    ("repost.aws/", "repost"),
)

_AVAILABILITY_KEYS = (
    ("products", "Product"),
    ("service_apis", "API"),
    ("cfn_resources", "CloudFormation resource"),
)


def _clean_title(text: str) -> str:
    """Collapse embedded newlines/whitespace runs so a title is always one line."""
    return " ".join(text.split())


def classify_url(url: str) -> str:
    """Category for a search hit, from its URL (docs, SDK/CDK refs, FAQs -> "")."""
    for marker, category in _URL_CATEGORIES:
        if marker in url:
            return category
    return ""


def render_search_item(item: dict[str, Any]) -> tuple[str, str, str]:
    title = _clean_title(item.get("title") or item.get("skill_name") or "(untitled)")
    url = item.get("url") or ""
    if not url and item.get("skill_name"):
        content = f"# {title}\n\nSkill: {item['skill_name']}\n\n{item.get('skill_description', '')}"
        return "skills", title, content
    content = f"# {title}\n\nURL: {url}\n\n{item.get('context', '')}"
    return classify_url(url), title, content


def _fallback_title(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1] or url


def _with_header(markdown: str, url: str, title: str, header_lines: Sequence[str]) -> str:
    """Put `URL: <url>` (and any warning lines) near the top so every file matches.

    Digest prompts look for a `URL:` line within the first lines of a file. When the
    page opens with its H1 the header goes right after it (same as `mslearn`);
    truncated reads open with a server-added redirect note / table of contents
    instead, so a synthesized H1 + header is prepended and the page text is kept
    verbatim (the TOC's char ranges are what `--start-index` jumps to).
    """
    lines = [f"URL: {url}", *header_lines]
    head = "\n".join(markdown.splitlines()[:_URL_LINE_SCAN_LINES])
    if _URL_LINE.search(head) and not header_lines:
        return markdown
    block = "\n".join(lines)
    stripped = markdown.lstrip("\n")
    first_line = stripped.split("\n", 1)[0]
    if _MARKDOWN_TITLE.fullmatch(first_line):
        after = stripped[len(first_line) :].lstrip("\n")
        return f"{first_line}\n\n{block}\n\n{after}"
    return f"# {title}\n\n{block}\n\n{markdown}"


def render_fetch_item(
    url: str,
    markdown: str,
    *,
    redirected_url: str | None = None,
    notes: Sequence[str] = (),
) -> tuple[str, str, str]:
    """One fetched page. `redirected_url` / `notes` become `> ` lines under the URL."""
    title_match = _MARKDOWN_TITLE.search(markdown)
    title = _clean_title(title_match.group(1) if title_match else _fallback_title(url))
    header_lines: list[str] = []
    if redirected_url:
        header_lines.append(
            f"> Warning: redirected to {redirected_url} -- the requested page may not exist."
        )
    header_lines += [f"> {note}" for note in notes]
    return "", title, _with_header(markdown, url, title, header_lines)


def render_skill(skill_name: str, file: str | None, body: str) -> tuple[str, str, str]:
    title = f"{skill_name}/{file}" if file else skill_name
    meta = f"Skill: {skill_name}" + (f"\nFile: {file}" if file else "")
    return "", title, f"# {title}\n\n{meta}\n\n{body}"


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    def row(cells: Sequence[str]) -> str:
        return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"

    return [row(headers), row(["---"] * len(headers)), *(row(r) for r in rows)]


def regions_table(regions: Sequence[dict[str, Any]]) -> list[str]:
    rows = [[r.get("region_id", ""), r.get("region_long_name", "")] for r in regions]
    return markdown_table(["Region", "Name"], rows)


def _status(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("status", ""))
    return str(value)


def availability_rows(
    result: dict[str, Any], regions: Sequence[str]
) -> tuple[list[str], list[list[str]]]:
    """Flatten `get_regional_availability` into (headers, rows).

    The server's shape differs by case: a single-region call maps each name straight
    to a status (``"isAvailableIn"`` or ``{"status": ...}``), a multi-region call maps
    each name to ``{region: status-or-{"status": ...}}``. Both become one row per
    name with one status column per requested region.
    """
    key, label = next(
        ((k, lbl) for k, lbl in _AVAILABILITY_KEYS if k in result),
        (None, "Name"),
    )
    mapping = (result.get(key) or {}) if key else {}
    columns = list(regions)
    rows: list[list[str]] = []
    for name, value in mapping.items():
        is_per_region = isinstance(value, dict) and "status" not in value
        if is_per_region:
            for region in value:
                if region not in columns:
                    columns.append(region)
            rows.append([name, *(_status(value.get(region, "")) for region in columns)])
        else:
            rows.append([name, _status(value)])
    if not columns:
        columns = ["status"]
    width = 1 + len(columns)
    rows = [r + [""] * (width - len(r)) for r in rows]
    return [label, *columns], rows
