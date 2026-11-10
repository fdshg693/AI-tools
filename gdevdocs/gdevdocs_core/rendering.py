"""Turn one MCP result item into a Markdown file body.

Search chunks expose ``parent`` / ``id`` / ``content``. Fetched documents expose
``title`` / ``uri`` / ``content`` / ``description`` / ``name``. Answers expose
``answerText`` and ``references``. ``URL:`` is always an ``https://`` URL: for a
search chunk that is ``https://`` plus the ``documents/`` name with that prefix
removed.
"""

from __future__ import annotations

from typing import Any


def document_name(value: str) -> str:
    """Accept a ``documents/...`` name or an ``http(s)`` URL. Anything else is an error."""
    text = value.strip()
    if text.startswith("documents/"):
        return text
    for scheme in ("https://", "http://"):
        if text.startswith(scheme):
            return "documents/" + text[len(scheme) :]
    raise ValueError(
        f"not a document name or URL: {text!r} (expected documents/... or an https:// URL)"
    )


def https_url_from_document_name(name: str) -> str:
    rest = name[len("documents/") :] if name.startswith("documents/") else name
    if rest.startswith("https://") or rest.startswith("http://"):
        return rest
    return "https://" + rest


def _last_segment(value: str) -> str:
    segment = value.rstrip("/").rsplit("/", 1)[-1].strip()
    return segment or "untitled"


def _compose(title: str, url: str, extras: list[str], body: str) -> str:
    block = "\n".join([f"URL: {url}", *extras])
    stripped = body.lstrip("\n")
    if stripped.startswith("# "):
        first, _, rest = stripped.partition("\n")
        return f"{first}\n\n{block}\n\n{rest.lstrip(chr(10))}"
    heading = title.strip() or "untitled"
    return f"# {heading}\n\n{block}\n\n{stripped}"


def render_search_item(item: dict[str, Any]) -> tuple[str, str]:
    parent = str(item.get("parent") or item.get("name") or "").strip()
    chunk_id = str(item.get("id") or "").strip()
    body = str(item.get("content") or "")
    url = https_url_from_document_name(parent) if parent else ""
    title = _last_segment(url or parent)
    extras: list[str] = []
    if parent:
        extras.append(f"Parent: {parent}")
    if chunk_id:
        extras.append(f"Id: {chunk_id}")
    return title, _compose(title, url, extras, body)


def render_document(doc: dict[str, Any]) -> tuple[str, str]:
    uri = str(doc.get("uri") or "").strip()
    name = str(doc.get("name") or "").strip()
    title = str(doc.get("title") or "").strip() or _last_segment(uri or name)
    description = str(doc.get("description") or "").strip()
    body = str(doc.get("content") or "")
    extras: list[str] = []
    if description:
        extras.append(description)
    if name:
        extras.append(f"Parent: {name}")
    return title, _compose(title, uri, extras, body)


def render_answer(query: str, payload: dict[str, Any]) -> tuple[str, str]:
    text = str(payload.get("answerText") or payload.get("answer_text") or "").rstrip()
    references = payload.get("references") or []
    lines = [f"# {query}", "", text, ""]
    if references:
        lines.append("## References")
        lines.extend(f"- {ref}" for ref in references)
        lines.append("")
    return query, "\n".join(lines).rstrip() + "\n"
