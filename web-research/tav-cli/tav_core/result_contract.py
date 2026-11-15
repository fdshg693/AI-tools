"""The CLI return contract shared by every `tav` wrapper script.

A caller never has to guess what a wrapper hands back: this module is the
authoritative source of truth for four contracts (the README tables describe the
same thing for humans — keep them in sync):

1. Process exit code -> ``ExitCode`` (an ``IntEnum``). Every ``main()`` returns
   one of these members; callers branch on the number.
2. Emitted data -> ``ResultEnvelope`` (a ``TypedDict``). Every script emits the
   SAME self-describing envelope, with a ``result_kind`` discriminator that tells
   the caller how to read ``result``. Where it lands depends on ``--topic`` (see
   ``OutputChannel`` and the writers in ``topic_layout``): stdout when absent,
   files under the topic folder when present.
3. Full audit log -> ``ResponseEnvelope`` (a ``TypedDict``), written to
   ``logs/<script>-log.json`` whenever logging is on (see ``environment``).
4. Output destination -> ``OutputChannel`` (an ``Enum``). Fixes *where* each of
   the above goes: stdout carries the machine-readable result and nothing else,
   every human/AI notice is a stderr ``DIAGNOSTIC``, and durable records are
   files. ``output.emit()`` is the single sink that routes by this enum.

It also carries the ``RunOutcome`` dataclass — the side-effect-free value a
``main()`` returns — plus the role-layout tables that decide which topic
subfolder a ``result_kind`` is filed under. This module is pure declarations:
no I/O, no Tavily calls (the per-item Tavily response shapes live in
``tavily_types``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any, TypedDict


# Shared ``--topic`` help, reused by every wrapper's ``--topic`` argument so the
# accumulate-into-role-subfolders contract is described in exactly one place (§4
# of PLAN.md "集約 vs 分割をコード/CLI ヘルプから明確化").
TOPIC_ARG_HELP = (
    "Accumulate this run into <TAVILY_OUTPUT_DIR>/NAME/. Discovery commands "
    "(search/map) append one list file under search/ or map/; content commands "
    "(extract/crawl) write one .md per page under pages/ (indexed by pages/index.json); "
    "research writes one .md under research/. Existing files are kept (never "
    "overwritten). Omit --topic to print one ResultEnvelope to stdout."
)

# ---------------------------------------------------------------------------
# Role-based topic layout (PLAN.md §0-§3). A ``--topic`` run's output is filed by
# the *role* of its ``result_kind`` — never one flat namespace — so the kinds of
# output (a discovery menu, fetched page bodies, a finished report) never mix:
#
#   discovery (search/map) -> aggregate JSON list, one file per task:
#                             <topic>/search/NNNN-<slug>.json or <topic>/map/...
#   content   (extract/crawl) -> one Markdown page per URL + a pages/index.json:
#                             <topic>/pages/NNNN-<slug>.md
#   report    (research) -> one Markdown report per question:
#                             <topic>/research/NNNN-<slug>.md (.json on failure)
#
# ``NNNN`` is allocated independently inside each subfolder (never a cross-role
# running number) and continues from the existing max on re-runs, so the same
# topic *accumulates* (appends) instead of overwriting.
# ---------------------------------------------------------------------------
ROLE_DISCOVERY = "discovery"
ROLE_CONTENT = "content"
ROLE_REPORT = "report"

ROLE_FOR_KIND: dict["ResultKind", str] = {}  # filled after ResultKind is defined
SUBDIR_FOR_KIND: dict["ResultKind", str] = {}  # role subfolder name per result_kind

# Projection allow-lists (PLAN.md §4③): the ONLY keys kept when a result item is
# written to a topic file or printed to stdout. Everything else (raw_content==None
# on search, empty images on extract, fetch metadata on site pages, ...) is research-
# irrelevant noise and dropped. The full untouched objects still live in the audit
# log. Edit these tuples to change what survives projection (applied by
# ``topic_layout.slim_result_item``).
PROJECTION_KEYS: dict["ResultKind", tuple[str, ...]] = {}  # filled after ResultKind


class ExitCode(IntEnum):
    """Authoritative process exit codes for every wrapper script.

    A script's ``main()`` MUST return one of these members (callers see the
    integer value as the process exit code). The same number is mirrored into
    ``ResultEnvelope["exit_code"]`` so a consumer reading only the emitted JSON
    can still recover the outcome without inspecting the process status.
    """

    SUCCESS = 0  # Completed; the result envelope holds the data.
    RUNTIME_ERROR = (
        1  # Unexpected failure (network/API error, or research finished failed/cancelled).
    )
    MISSING_API_KEY = 2  # TAVILY_API_KEY missing or empty after loading the environment.
    INVALID_API_KEY = 3  # The key was rejected by Tavily.
    EMPTY_RESULT = 4  # The call succeeded but yielded no actionable data (e.g. no URLs to extract).
    INCOMPLETE = (
        5  # A long-running op (research) did not reach a terminal state within the wait window.
    )


class ResultKind(str, Enum):
    """Discriminator for ``ResultEnvelope["result"]``.

    Tells the caller how to interpret ``result`` without reading the producing
    script's source. ``str`` mixin so the value serializes as a plain string.
    The concrete element type each member names is defined in ``tavily_types``
    (e.g. ``SEARCH_RESULTS`` -> ``list[SearchResultItem]``).
    """

    SEARCH_RESULTS = "search_results"  # list[SearchResultItem]: Tavily search result objects.
    EXTRACT_RESULTS = "extract_results"  # list[ExtractResultItem]: Tavily extract result objects.
    CRAWL_RESULTS = "crawl_results"  # list[CrawlResultItem]: Tavily crawl result objects.
    SITE_PAGES = (
        "site_pages"  # list[SitePageItem]: page-title records (see PageTitleResult / SitePageItem).
    )
    RESEARCH_REPORT = (
        "research_report"  # str (markdown report) on success, else the raw final response dict.
    )


# Populate the role-layout tables now that ResultKind exists (see the role-layout
# block above for what each entry means).
ROLE_FOR_KIND.update(
    {
        ResultKind.SEARCH_RESULTS: ROLE_DISCOVERY,
        ResultKind.SITE_PAGES: ROLE_DISCOVERY,
        ResultKind.EXTRACT_RESULTS: ROLE_CONTENT,
        ResultKind.CRAWL_RESULTS: ROLE_CONTENT,
        ResultKind.RESEARCH_REPORT: ROLE_REPORT,
    }
)
SUBDIR_FOR_KIND.update(
    {
        ResultKind.SEARCH_RESULTS: "search",
        ResultKind.SITE_PAGES: "map",
        ResultKind.EXTRACT_RESULTS: "pages",
        ResultKind.CRAWL_RESULTS: "pages",
        ResultKind.RESEARCH_REPORT: "research",
    }
)
PROJECTION_KEYS.update(
    {
        # search rows: triage columns only. raw_content is always None under our flags.
        ResultKind.SEARCH_RESULTS: ("url", "title", "content", "score"),
        # extract pages: identity + body. images is always empty under our flags.
        ResultKind.EXTRACT_RESULTS: ("url", "title", "raw_content"),
        # crawl pages: url + body only (crawl items never carry a title).
        ResultKind.CRAWL_RESULTS: ("url", "raw_content"),
        # site-page menu: url + readable titles; fetch metadata is dropped.
        ResultKind.SITE_PAGES: ("url", "title", "short_title"),
        # research_report has no per-item projection (it is a single str/dict).
    }
)


def role_for(result_kind: ResultKind) -> str:
    """The output role (discovery / content / report) a ``result_kind`` belongs to.

    This 3-way dispatch is the single source of truth for "where does this land":
    discovery -> a list file under search/ or map/, content -> Markdown pages
    under pages/, report -> a Markdown report under research/ (see ROLE_FOR_KIND).
    """
    return ROLE_FOR_KIND[result_kind]


class OutputChannel(str, Enum):
    """Authoritative set of destinations a run may write to (the 4th contract).

    Alongside ``ExitCode`` (the outcome), ``ResultEnvelope`` (the data) and
    ``ResponseEnvelope`` (the record), this enum fixes *where* each kind of
    output goes, so a caller never has to guess which stream carries data and
    which carries noise. Every byte the package emits passes through
    ``output.emit()`` tagged with one of these members, and that is the ONLY
    place output happens.

    The discipline these members encode:

    - stdout carries the machine-readable result and NOTHING else
      (``RESULT_STDOUT``), so a caller can parse stdout verbatim.
    - Every human/AI-facing notice is a ``DIAGNOSTIC`` on stderr; it is never
      structured and never lands on stdout.
    - Durable records are files: the public envelope (``RESULT_FILE``) and the
      full audit log (``AUDIT_LOG``).
    """

    RESULT_STDOUT = "result_stdout"  # ResultEnvelope JSON -> stdout (only when --topic is absent).
    RESULT_FILE = "result_file"  # .json (discovery list / index / failed report) or .md (page / report) -> a topic-folder file.
    AUDIT_LOG = "audit_log"  # ResponseEnvelope JSON -> logs/<script>-log.json (when logging is on).
    DIAGNOSTIC = (
        "diagnostic"  # one human/AI-facing line -> stderr (never stdout, never structured).
    )


class EnvironmentInfo(TypedDict):
    """Environment provenance recorded in every ``ResponseEnvelope``."""

    config_files: list[str]  # config files in reach, precedence order (nearest project -> global)
    setting_sources: dict[str, str]  # setting -> "env:<NAME>" | config-file path | "default"
    api_key_present: bool


class ResponseEnvelope(TypedDict):
    """Full audit record written to ``logs/<script>-log.json`` (when enabled).

    Written whenever logging is on (see ``environment.should_write_log``, default
    on). This is the verbose, reproduce-everything view. The slim public output is
    ``ResultEnvelope`` instead.
    """

    script: str
    request: dict[str, Any]
    environment: EnvironmentInfo
    response: dict[str, Any]


class ResultEnvelope(TypedDict):
    """Self-describing payload emitted to stdout or a topic-folder file.

    Every wrapper script emits this exact top-level shape. ``result_kind`` is the
    discriminator; ``result`` holds the data whose shape it names. ``exit_code``
    mirrors the process exit code so the file alone is enough to know the outcome.
    In the split layout, each per-URL file is one of these with ``result`` set to
    a single content item rather than a list.
    """

    script: str
    result_kind: str  # one of ResultKind's values
    exit_code: int  # one of ExitCode's values
    result: Any  # shape determined by result_kind


@dataclass(slots=True)
class TopicArtifact:
    """A secondary role-output a run also wants persisted under ``--topic``.

    Composite commands produce two artifacts of *different roles*: the discovery
    menu they searched/mapped AND the page content they then extracted. ``main()``
    returns the content as the primary ``RunOutcome.result`` and the discovery
    menu as ``RunOutcome.discovery`` (one of these), so "what was searched" and
    "what was fetched" both land in the topic folder, each in its own role
    subfolder. ``slug`` names the task (query / domain) for the ``NNNN-<slug>`` file.
    """

    result_kind: ResultKind
    result: Any
    slug: str | None = None


@dataclass(slots=True)
class BackgroundTask:
    """A fully detached follow-on process a run wants launched after it returns.

    The wrapper scripts block their caller (often an AI agent) only briefly. A
    long-running op — today only ``research`` — whose foreground wait expires
    returns ``INCOMPLETE`` immediately AND attaches one of these so the work is
    not abandoned: ``topic_layout.finalize()`` (the sole side-effect site) spawns
    ``argv`` as a detached process that outlives this one and finishes the job.
    ``main()`` stays pure by merely *describing* the process to launch; nothing is
    spawned until ``finalize()`` runs. ``argv`` is the complete command
    (interpreter + script + args); ``cwd`` fixes the working directory so
    output-dir resolution matches the parent (see ``environment.get_output_dir``).
    """

    argv: list[str]
    cwd: str | None = None


@dataclass(slots=True)
class RunOutcome:
    """The complete, side-effect-free return value of a script's ``main()``.

    This is the contract between the functional core (``main()``) and the
    imperative shell (``topic_layout.finalize()``): ``main()`` builds and returns
    one of these without writing anything, then ``finalize()`` performs all the
    I/O it implies.

    - ``exit_code``: the process exit code to report (always present).
    - ``log`` + ``result_kind`` + ``result``: the data to emit. All three are set
      on a run that reached the request stage; all three stay ``None`` on an early
      failure (e.g. missing credentials) where there is nothing to emit.
    - ``topic``: the ``--topic`` value. When set, ``finalize()`` files the result
      into ``<TAVILY_OUTPUT_DIR>/<topic>/`` under the role subfolder for
      ``result_kind`` (search/ map/ pages/ research/). When ``None``, the single
      ``ResultEnvelope`` goes to stdout (pipe use).
    - ``slug``: task-level slug hint for the ``NNNN-<slug>`` file name of the
      discovery/report writers (the search query, the mapped domain, the research
      question). Ignored by the content writer, which slugs each page from its own
      title. ``None`` falls back to a generic stem.
    - ``discovery``: an optional second ``TopicArtifact`` (composite commands only)
      filed alongside the primary result in its own role subfolder; ignored on the
      stdout path so the pipe contract stays one envelope.
    - ``message``: a single stderr line to print, if any (errors, empty/incomplete
      notices). ``None`` means stay silent on stderr.
    - ``background``: an optional ``BackgroundTask`` ``finalize()`` spawns detached
      after emitting this run's output. Used by ``research`` to keep polling a job
      whose foreground wait expired. ``None`` means no follow-on process.
    """

    exit_code: ExitCode
    topic: str | None = None
    log: ResponseEnvelope | None = None
    result_kind: ResultKind | None = None
    result: Any = None
    message: str | None = None
    slug: str | None = None
    discovery: TopicArtifact | None = None
    background: BackgroundTask | None = None
