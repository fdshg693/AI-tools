"""Role-based topic-folder writers: decide *what* output goes *where*.

This module owns the ``--topic`` layout and nothing else. Given a ``--topic``,
output is filed by the *role* of its ``result_kind`` (see ``result_contract``
ROLE tables) so the kinds never mix:

  discovery (search/map) -> one aggregated JSON list per task under search/ or map/
  content   (extract/crawl) -> one Markdown page per URL under pages/ + index.json
  report    (research) -> one Markdown report under research/ (success only)

Without a ``--topic``, a single projected ``ResultEnvelope`` goes to stdout.
``emit_payload`` is the entry point (called by ``run_shell.finalize``); it writes
the audit log, then dispatches to the per-role writers (topic path) or stdout. It
borrows item shaping from ``projection`` and the single output sink from
``output`` — it only decides destinations, never how a run is finalized
(``run_shell``) or which keys survive (``projection``).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from tav_core.environment import get_output_dir, should_show_log_path, should_write_log
from tav_core.output import (
    build_log_output_path,
    build_result_envelope,
    emit,
)
from tav_core.page_title import (
    DEFAULT_TITLE_OPTIONS,
    build_title_from_url,
    fetch_page_title,
)
from tav_core.projection import project_result, slim_result_item
from tav_core.result_contract import (
    ROLE_CONTENT,
    ROLE_REPORT,
    SUBDIR_FOR_KIND,
    ExitCode,
    OutputChannel,
    ResponseEnvelope,
    ResultKind,
    TopicArtifact,
    role_for,
)
from tav_core.text_utils import slugify


INDEX_FILE_NAME = "index.json"

_SEQUENCE_PREFIX = re.compile(r"^(\d{4})")


def resolve_output_target(topic: str, *, output_dir: Path | None = None) -> Path:
    """Resolve the topic folder ``<TAVILY_OUTPUT_DIR>/<topic>/`` for ``--topic``.

    ``topic`` is used as a single folder name; any stray path separators are
    flattened to ``_`` so it can never escape the output directory.
    """
    base = output_dir if output_dir is not None else get_output_dir()
    safe_topic = topic.strip().replace("\\", "_").replace("/", "_") or "topic"
    return base / safe_topic


def next_sequence(directory: Path) -> int:
    """Next ``NNNN`` to allocate inside one role subfolder (existing max + 1).

    Scans for files whose name starts with a 4-digit number and returns one past
    the highest, so re-running the same topic *appends* (``0003`` after ``0002``)
    rather than overwriting. Sequencing is per-subfolder, so search/ and pages/
    keep independent series. Assumes sequential (non-concurrent) runs against a
    topic — parallel allocation could collide.
    """
    if not directory.exists():
        return 1
    highest = 0
    for entry in directory.iterdir():
        match = _SEQUENCE_PREFIX.match(entry.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def render_page_markdown(title: str | None, body: str | None) -> str:
    """Render one fetched page as ``# <title>`` + body Markdown (content role).

    The body (Tavily's ``raw_content``, already Markdown under our ``format``
    flag) is written as-is — far more readable than the same text escaped inside a
    JSON string. ``images`` / fetch metadata are intentionally NOT carried in (the
    projection already dropped them); url<->file<->title structure lives in
    ``pages/index.json``.
    """
    heading = (title or "Untitled").strip() or "Untitled"
    body_text = (body or "").strip()
    if body_text:
        return f"# {heading}\n\n{body_text}\n"
    return f"# {heading}\n"


def emit_payload(
    payload: ResponseEnvelope,
    *,
    topic: str | None,
    result_kind: ResultKind,
    result: Any,
    exit_code: ExitCode = ExitCode.SUCCESS,
    slug: str | None = None,
    discovery: TopicArtifact | None = None,
    pretty: bool = True,
) -> None:
    """Emit a run's record artifacts, routed through ``output.emit()``.

    Audit log: the full, unprojected ``ResponseEnvelope`` -> ``logs/<script>-log.json``
    (``AUDIT_LOG``), only when ``should_write_log()`` is true.

    Result, by ``topic``:

    - ``topic is None``: a single ``ResultEnvelope`` (with ``result`` *projected*
      to research-relevant keys) -> stdout (``RESULT_STDOUT``). The pipe contract
      stays one envelope; ``discovery`` is ignored here.
    - ``topic`` set: filed into ``<TAVILY_OUTPUT_DIR>/<topic>/`` by ``result_kind``'s
      role — discovery (a list file under search/ or map/), content (Markdown pages
      under pages/ + index), or report (a Markdown report under research/). A
      ``discovery`` artifact, when present, is filed alongside in its own role
      subfolder so a composite run keeps both its menu and its fetched bodies.

    Every accompanying notice is a ``DIAGNOSTIC`` on stderr. Result/output file
    path notices are always shown; only the audit-log path notice is gated by
    ``should_show_log_path()``.
    """
    script_name = payload.get("script", "payload")

    if should_write_log():
        log_path = build_log_output_path(script_name=script_name)
        emit(OutputChannel.AUDIT_LOG, payload, path=log_path, pretty=pretty)
        if should_show_log_path():
            emit(OutputChannel.DIAGNOSTIC, f"Wrote full log to {log_path}")

    if topic is None:
        result_envelope = build_result_envelope(
            script_name=script_name,
            result_kind=result_kind,
            result=project_result(result_kind, result),
            exit_code=exit_code,
        )
        emit(OutputChannel.RESULT_STDOUT, result_envelope, pretty=pretty)
        return

    target_dir = resolve_output_target(topic)
    write_topic_artifact(
        target_dir,
        script_name=script_name,
        result_kind=result_kind,
        result=result,
        slug=slug,
        exit_code=exit_code,
        topic=topic,
        pretty=pretty,
    )
    if discovery is not None:
        write_topic_artifact(
            target_dir,
            script_name=script_name,
            result_kind=discovery.result_kind,
            result=discovery.result,
            slug=discovery.slug,
            exit_code=exit_code,
            topic=topic,
            pretty=pretty,
        )


def write_topic_artifact(
    target_dir: Path,
    *,
    script_name: str,
    result_kind: ResultKind,
    result: Any,
    slug: str | None,
    exit_code: ExitCode,
    topic: str,
    pretty: bool = True,
) -> None:
    """Dispatch one (result_kind, result) to its role writer under ``target_dir``.

    The role (``role_for``) picks both the writer and the subfolder
    (``SUBDIR_FOR_KIND``): discovery -> ``write_discovery_list``, content ->
    ``write_content_pages``, report -> ``write_report``.
    """
    role = role_for(result_kind)
    role_dir = target_dir / SUBDIR_FOR_KIND[result_kind]
    if role == ROLE_CONTENT:
        write_content_pages(
            role_dir,
            script_name=script_name,
            result_kind=result_kind,
            result=result,
            exit_code=exit_code,
            topic=topic,
            pretty=pretty,
        )
    elif role == ROLE_REPORT:
        write_report(
            role_dir,
            script_name=script_name,
            result_kind=result_kind,
            result=result,
            slug=slug,
            exit_code=exit_code,
            pretty=pretty,
        )
    else:
        write_discovery_list(
            role_dir,
            script_name=script_name,
            result_kind=result_kind,
            result=result,
            slug=slug,
            exit_code=exit_code,
            pretty=pretty,
        )


def write_discovery_list(
    role_dir: Path,
    *,
    script_name: str,
    result_kind: ResultKind,
    result: Any,
    slug: str | None,
    exit_code: ExitCode,
    pretty: bool = True,
) -> None:
    """Discovery role: append one projected list file ``NNNN-<slug>.json``.

    ``search`` / ``map`` menus are skimmed as a table AND fed to the next extract
    step, so they stay machine-readable JSON and stay *aggregated* (one task = one
    file): splitting a 5-row menu across 5 files would destroy its at-a-glance
    value. No side index — the file name is self-describing (``ls`` is enough).
    """
    items = [
        slim_result_item(result_kind, item) for item in (result or []) if isinstance(item, dict)
    ]
    sequence = next_sequence(role_dir)
    file_name = f"{sequence:04d}-{slugify(slug)}.json"
    envelope = build_result_envelope(
        script_name=script_name,
        result_kind=result_kind,
        result=items,
        exit_code=exit_code,
    )
    file_path = role_dir / file_name
    emit(OutputChannel.RESULT_FILE, envelope, path=file_path, pretty=pretty)
    emit(OutputChannel.DIAGNOSTIC, f"Wrote {len(items)} {result_kind.value} row(s) to {file_path}")


def write_report(
    research_dir: Path,
    *,
    script_name: str,
    result_kind: ResultKind,
    result: Any,
    slug: str | None,
    exit_code: ExitCode,
    pretty: bool = True,
) -> None:
    """Report role: write one ``NNNN-<slug>.md`` report ONLY on success.

    A successful run (a Markdown ``str``) is written as ``.md`` so it reads
    straight through. Any non-success outcome — the foreground wait expiring
    (``INCOMPLETE``) or a failed/cancelled terminal (``RUNTIME_ERROR``) — writes
    NO file: research output is "the report or nothing", so a timed-out/failed
    run must not leave a half-baked ``.json`` artifact in ``research/``. The
    failure is still fully recorded in the audit log (``logs/<script>-log.json``),
    and for a foreground timeout a detached poller (``research_background_poll.py``)
    keeps going and writes the real ``.md`` here if the job later completes.
    """
    if exit_code == ExitCode.SUCCESS and isinstance(result, str):
        sequence = next_sequence(research_dir)
        file_path = research_dir / f"{sequence:04d}-{slugify(slug)}.md"
        markdown = result if result.endswith("\n") else result + "\n"
        emit(OutputChannel.RESULT_FILE, markdown, path=file_path, pretty=pretty)
        emit(OutputChannel.DIAGNOSTIC, f"Wrote research report to {file_path}")
        return
    emit(
        OutputChannel.DIAGNOSTIC,
        "Research produced no report (non-success outcome); wrote no file. "
        "See the audit log for the failure detail.",
    )


def ensure_item_titles(items: Sequence[dict[str, Any]]) -> list[tuple[str, str]]:
    """Resolve a ``(title, title_source)`` for each content item.

    An item that already carries a non-empty ``title`` keeps it
    (``title_source="existing"``); one without (notably ``crawl`` items) has its
    title back-filled via a direct HTML fetch — never Tavily — falling back to a
    URL-derived slug. Missing titles are fetched concurrently.
    """
    resolved: list[tuple[str, str] | None] = [None] * len(items)
    to_fetch: list[int] = []
    for index, item in enumerate(items):
        existing = (item.get("title") or "").strip()
        if existing:
            resolved[index] = (existing, "existing")
        else:
            to_fetch.append(index)

    if to_fetch:

        def fetch(index: int) -> tuple[str, str]:
            url = (items[index].get("url") or "").strip()
            if not url:
                return (build_title_from_url(""), "url_fallback")
            page = fetch_page_title(
                url,
                timeout_seconds=DEFAULT_TITLE_OPTIONS["timeout_seconds"],
                max_bytes=DEFAULT_TITLE_OPTIONS["max_bytes"],
            )
            return (page.title, page.title_source)

        max_workers = min(DEFAULT_TITLE_OPTIONS["max_workers"], len(to_fetch))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for index, pair in zip(to_fetch, executor.map(fetch, to_fetch)):
                resolved[index] = pair

    return [pair if pair is not None else ("", "url_fallback") for pair in resolved]


def load_pages_index(pages_dir: Path, *, topic: str) -> dict[str, Any]:
    """Load ``pages/index.json`` for append, or seed a fresh one.

    The index is the ONE shared file the content role accumulates (its ``entries``
    grow across runs). An unreadable / old-schema file is discarded and rebuilt
    (no migration), so a corrupt index never blocks a run.
    """
    import json

    index_path = pages_dir / INDEX_FILE_NAME
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = None
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data
    return {"topic": topic, "entries": []}


def write_content_pages(
    pages_dir: Path,
    *,
    script_name: str,
    result_kind: ResultKind,
    result: Any,
    exit_code: ExitCode,
    topic: str,
    pretty: bool = True,
) -> None:
    """Content role: one Markdown page per URL + an appended ``pages/index.json``.

    Page bodies are *split* (one ``NNNN-<slug>.md`` each) because they are large
    and read one at a time; aggregating them would be unreadable. Titles are
    back-filled first (``ensure_item_titles`` — direct HTML fetch, never Tavily) so
    each page gets a self-describing slug + H1 and the index carries a real title.
    Sequence numbers continue from the existing pages (append, never overwrite);
    re-extracting the same URL adds another page + index entry (duplicates kept).
    ``pages/index.json`` is the only url<->file<->title<->source map. Each entry
    also carries ``char_count`` (``len(markdown)``, the exact ``.md`` file length)
    so a caller can decide, per page, whether to Read it directly or route it
    through ``aim --parallel`` instead (``tav-digest`` skill) — no aggregate is computed.
    """
    items: list[dict[str, Any]] = [item for item in (result or []) if isinstance(item, dict)]
    titles = ensure_item_titles(items)

    index = load_pages_index(pages_dir, topic=topic)
    start = next_sequence(pages_dir)
    written_files: list[tuple[str, str]] = []
    for offset, (item, (title, title_source)) in enumerate(zip(items, titles)):
        sequence = start + offset
        file_name = f"{sequence:04d}-{slugify(title)}.md"
        markdown = render_page_markdown(title, item.get("raw_content"))
        emit(OutputChannel.RESULT_FILE, markdown, path=pages_dir / file_name, pretty=pretty)
        index["entries"].append(
            {
                "file": file_name,
                "url": item.get("url"),
                "title": title,
                "title_source": title_source,
                "script": script_name,
                "result_kind": result_kind.value,
                "exit_code": int(exit_code),
                "char_count": len(markdown),
            }
        )
        written_files.append((file_name, item.get("url") or ""))

    index_path = pages_dir / INDEX_FILE_NAME
    emit(OutputChannel.RESULT_FILE, index, path=index_path, pretty=pretty)
    written = len(written_files)
    summary = f"Wrote {written} page .md file(s) to {pages_dir}"
    if written_files:
        listing = "\n".join(f"  {file_name} <- {url}" for file_name, url in written_files)
        summary = f"{summary}:\n{listing}"
    emit(
        OutputChannel.DIAGNOSTIC,
        f"{summary}\n(index now has {len(index['entries'])} entr(ies) at {index_path})",
    )
