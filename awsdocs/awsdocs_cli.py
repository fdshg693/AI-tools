r"""CLI entry point wrapping the official AWS Knowledge MCP server.

The server (https://knowledge-mcp.global.api.aws) needs no auth and exposes five
tools as of this writing, all prefixed ``aws___``: ``search_documentation``,
``read_documentation``, ``list_regions``, ``get_regional_availability``,
``retrieve_skill``. This module only wires argparse subcommands to the building
blocks in ``awsdocs_core``:

- ``awsdocs_core.client``    talks to the MCP server (one fastmcp.Client session
  per run, 429 retried once).
- ``awsdocs_core.responses`` turns the server's always-``is_error=False`` replies
  into data or typed errors (see ``memo/01-knowledge-mcp-server.md``).
- ``awsdocs_core.rendering`` turns one raw result item into a (category, title,
  markdown) triple, and builds the ``regions`` / ``availability`` tables.
- ``awsdocs_core.output``    writes those triples into one numbered folder per
  call (Blog / What's New / re:Post / skill results under subfolders) with an
  ``index.md`` summary, and prints only the ``index.md`` path.

``search`` / ``fetch`` / ``skill`` write every result under a fresh
``NNNN-<slug>/`` folder inside ``AWSDOCS_MCP_OUTPUT_DIR`` and print only the
``index.md`` path back -- never per-file paths or content -- so a caller's
context isn't spent on page bodies it didn't ask to see yet. ``regions`` /
``availability`` are small and print a Markdown table to stdout. ``--json``
switches every subcommand to a single JSON object on stdout and skips file
writing entirely, for piping into `jq` or another CLI.

Example (after installing the `awsdocs` console script -- see README.md):
    awsdocs search "S3 lifecycle rule transition to Glacier"
    awsdocs fetch https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-configuration-examples.html --all
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent

from awsdocs_core import client, rendering, responses
from awsdocs_core.config import (
    AVAILABILITY_TOOL,
    AVAILABILITY_TYPES,
    DEFAULT_ENDPOINT,
    DEFAULT_SEARCH_LIMIT,
    DEFAULT_TIMEOUT,
    ENDPOINT_ENV,
    EXIT_EMPTY_RESULT,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    EXIT_TOOL_ERROR,
    LIST_REGIONS_TOOL,
    MAX_AVAILABILITY_REGIONS,
    MAX_READ_ROUNDS,
    MAX_TOPICS,
    READ_BATCH_SIZE,
    READ_TOOL,
    SEARCH_TOOL,
    SEARCH_TOPICS,
    SKILL_TOOL,
    TOOL_PREFIX,
)
from awsdocs_core.output import print_index_path, write_query_results

EMPTY_RESPONSE_HINT = (
    "the server returned no content for this range (a known server-side quirk on some "
    "long pages); retry with a different --start-index / --max-length, or fetch the page's "
    ".md URL directly"
)


def tool_version() -> str:
    data = tomllib.loads((TOOL_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a single JSON object to stdout with full content inline instead of writing result files (for piping into jq etc.); never writes a file.",
    )
    parser.add_argument(
        "--endpoint",
        help=f"Override the MCP endpoint (default: {ENDPOINT_ENV} env var, else {DEFAULT_ENDPOINT}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def call_and_unwrap(args: argparse.Namespace, tool_name: str, arguments: dict[str, Any]) -> Any:
    endpoint = client.resolve_endpoint(args.endpoint)
    return responses.unwrap(client.call_tool(endpoint, args.timeout, tool_name, arguments))


def cmd_search(args: argparse.Namespace) -> int:
    arguments: dict[str, Any] = {"search_phrase": args.query, "limit": args.limit}
    if args.topic:
        arguments["topics"] = args.topic
    content = call_and_unwrap(args, SEARCH_TOOL, arguments)

    # Never "empty" in practice: the server returns *something* even for nonsense
    # queries, so relevance can't be judged here. Only a literally empty list is 4.
    results = (content or {}).get("result") or []
    if not results:
        print("No results.", file=sys.stderr)
        return EXIT_EMPTY_RESULT

    if args.json:
        print_json({"query": args.query, "topics": args.topic or [], "results": results})
        return EXIT_SUCCESS

    index_path = write_query_results(
        args.query, [rendering.render_search_item(item) for item in results]
    )
    print_index_path(index_path)
    return EXIT_SUCCESS


@dataclass
class FetchState:
    """Accumulated result for one requested URL across `fetch --all` rounds."""

    url: str
    next_start: int
    content: str = ""
    chunks: int = 0
    total_length: int | None = None
    end_index: int | None = None
    truncated: bool = False
    redirected_url: str | None = None
    failure: str | None = None
    failure_kind: str | None = None  # "tool" | "empty" | "throttled"


def _chunks(values: list[int], size: int):
    for i in range(0, len(values), size):
        yield values[i : i + size]


def _apply_read_item(state: FetchState, item: dict[str, Any], follow: bool) -> bool:
    """Merge one read result into `state`; return True if another round is needed."""
    if item.get("status") != "SUCCESS":
        code = item.get("error_code")
        message = item.get("content") or ""
        state.failure_kind = "throttled" if code == "throttled" else "tool"
        state.failure = ": ".join(part for part in (code, message) if part) or "unknown error"
        return False
    if not (item.get("content") or "").strip():
        state.failure_kind = "empty"
        state.failure = EMPTY_RESPONSE_HINT
        return False

    state.content += item["content"] if state.chunks == 0 else responses.chunk_body(item)
    state.chunks += 1
    state.redirected_url = state.redirected_url or item.get("redirected_url")
    state.total_length = item.get("total_length")
    start = item.get("start_index") or 0
    end = item.get("end_index")
    state.end_index = end
    state.truncated = bool(item.get("truncated"))
    if follow and state.truncated and isinstance(end, int) and end > start:
        state.next_start = end
        return True
    return False


async def _read_all(
    session: client.Session, states: list[FetchState], max_length: int | None, follow: bool
) -> None:
    pending = list(range(len(states)))
    rounds = 0
    while pending and rounds < MAX_READ_ROUNDS:
        rounds += 1
        next_pending: list[int] = []
        for batch in _chunks(pending, READ_BATCH_SIZE):
            requests = []
            for i in batch:
                request: dict[str, Any] = {"url": states[i].url}
                if states[i].next_start:
                    request["start_index"] = states[i].next_start
                if max_length is not None:
                    request["max_length"] = max_length
                requests.append(request)
            result = await session.call_tool(READ_TOOL, {"requests": requests})
            try:
                items = (responses.unwrap(result) or {}).get("result") or []
            except responses.EmptyResponseError:
                items = [{"status": "SUCCESS", "content": ""}] * len(batch)
            except responses.ToolResponseError as exc:
                items = [{"status": "ERROR", "content": str(exc)}] * len(batch)
            if len(items) != len(batch):
                raise RuntimeError(
                    f"read_documentation returned {len(items)} results for {len(batch)} URLs"
                )
            for i, item in zip(batch, items):
                if _apply_read_item(states[i], item, follow):
                    next_pending.append(i)
        pending = next_pending


def _fetch_notes(state: FetchState, follow: bool) -> list[str]:
    notes: list[str] = []
    if state.failure and state.chunks:
        notes.append(f"Incomplete: reading stopped at char {state.end_index} ({state.failure}).")
    elif state.truncated and state.end_index is not None:
        verb = "Stopped after the round limit" if follow else "Truncated"
        notes.append(
            f"{verb} at char {state.end_index} of {state.total_length}; "
            f"continue with --start-index {state.end_index} or use --all."
        )
    return notes


def cmd_fetch(args: argparse.Namespace) -> int:
    states = [FetchState(url=url, next_start=args.start_index or 0) for url in args.urls]
    endpoint = client.resolve_endpoint(args.endpoint)
    client.run(
        endpoint,
        args.timeout,
        lambda session: _read_all(session, states, args.max_length, args.all),
    )

    for state in states:
        if state.redirected_url:
            print(
                f"Warning: {state.url} was redirected to {state.redirected_url} "
                "(the requested page may not exist).",
                file=sys.stderr,
            )
        if state.failure:
            print(f"Failed: {state.url}: {state.failure}", file=sys.stderr)
            if state.failure_kind == "throttled":
                print("Rate limited by the server; wait a while and retry.", file=sys.stderr)

    if args.json:
        print_json(
            {
                "results": [
                    {
                        "url": s.url,
                        "status": "ERROR" if s.failure and not s.chunks else "SUCCESS",
                        "content": s.content,
                        "total_length": s.total_length,
                        "end_index": s.end_index,
                        "truncated": s.truncated,
                        "redirected_url": s.redirected_url,
                        "error": s.failure,
                    }
                    for s in states
                ]
            }
        )
    else:
        items: list[tuple[str, str, str]] = []
        warnings: list[str] = []
        errors: list[str] = []
        for state in states:
            if state.failure and not state.chunks:
                errors.append(f"{state.url}: {state.failure}")
                continue
            notes = _fetch_notes(state, args.all)
            items.append(
                rendering.render_fetch_item(
                    state.url, state.content, redirected_url=state.redirected_url, notes=notes
                )
            )
            filename = f"{len(items):04d}.md"
            if state.redirected_url:
                warnings.append(f"{filename}: {state.url} redirected to {state.redirected_url}")
            warnings += [f"{filename}: {note}" for note in notes]
        if items:
            label = (
                args.urls[0]
                if len(args.urls) == 1
                else f"{args.urls[0]} (+{len(args.urls) - 1} more)"
            )
            print_index_path(write_query_results(label, items, warnings=warnings, errors=errors))

    kinds = {s.failure_kind for s in states if s.failure}
    if kinds & {"empty", "throttled"}:
        return EXIT_RUNTIME_ERROR
    if kinds:
        return EXIT_TOOL_ERROR
    return EXIT_SUCCESS


def cmd_regions(args: argparse.Namespace) -> int:
    content = call_and_unwrap(args, LIST_REGIONS_TOOL, {})
    regions = (content or {}).get("result") or []
    if not regions:
        print("No regions returned.", file=sys.stderr)
        return EXIT_EMPTY_RESULT
    if args.json:
        print_json(regions)
    else:
        print("\n".join(rendering.regions_table(regions)))
    return EXIT_SUCCESS


def cmd_availability(args: argparse.Namespace) -> int:
    arguments: dict[str, Any] = {"resource_type": args.type, "regions": args.region}
    if args.filter:
        arguments["filters"] = args.filter
    if args.next_token:
        arguments["next_token"] = args.next_token
    result = (call_and_unwrap(args, AVAILABILITY_TOOL, arguments) or {}).get("result") or {}

    headers, rows = rendering.availability_rows(result, args.region)
    if args.json:
        print_json(result)
    elif rows:
        print("\n".join(rendering.markdown_table(headers, rows)))
    if result.get("failed_regions"):
        print(f"Warning: failed regions: {result['failed_regions']}", file=sys.stderr)
    if result.get("next_token"):
        print(f"More results: --next-token {result['next_token']}", file=sys.stderr)
    if not rows:
        print("No availability data returned.", file=sys.stderr)
        return EXIT_EMPTY_RESULT
    return EXIT_SUCCESS


def cmd_skill(args: argparse.Namespace) -> int:
    arguments: dict[str, Any] = {"skill_name": args.skill_name}
    if args.file:
        arguments["file"] = args.file
    content = call_and_unwrap(args, SKILL_TOOL, arguments) or {}
    body = content.get("skill_content") or ""
    if not body.strip():
        print(f"Skill {args.skill_name} returned no content.", file=sys.stderr)
        return EXIT_EMPTY_RESULT

    if args.json:
        print_json({"skill_name": args.skill_name, "file": args.file, "content": body})
        return EXIT_SUCCESS

    label = f"skill {args.skill_name}" + (f" {args.file}" if args.file else "")
    index_path = write_query_results(
        label, [rendering.render_skill(args.skill_name, args.file, body)]
    )
    print_index_path(index_path)
    return EXIT_SUCCESS


def cmd_tools(args: argparse.Namespace) -> int:
    endpoint = client.resolve_endpoint(args.endpoint)
    tools = client.list_tools(endpoint, args.timeout)

    if args.json:
        print_json([t.model_dump(mode="json") for t in tools])
        return EXIT_SUCCESS

    for tool in tools:
        schema = getattr(tool, "input_schema", None)
        if schema is None:
            schema = tool.inputSchema
        print(
            f"## {tool.name}\n{tool.description or ''}\nSchema: {json.dumps(schema, ensure_ascii=False)}\n"
        )
    return EXIT_SUCCESS


def resolve_tool_name(name: str, no_prefix: bool) -> str:
    """Add the server's `aws___` prefix unless it's already there (or `--no-prefix`)."""
    if no_prefix or name.startswith(TOOL_PREFIX):
        return name
    return TOOL_PREFIX + name


def cmd_call(args: argparse.Namespace) -> int:
    endpoint = client.resolve_endpoint(args.endpoint)
    try:
        arguments = json.loads(args.args) if args.args else {}
    except json.JSONDecodeError as exc:
        print(f"--args is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR

    tool_name = resolve_tool_name(args.tool_name, args.no_prefix)
    result = client.call_tool(endpoint, args.timeout, tool_name, arguments)
    error_message = responses.error_message_of(result)

    if args.json:
        print_json(
            {
                "tool": tool_name,
                "is_error": result.is_error or error_message is not None,
                "structured_content": result.structured_content,
                "content_text": client.content_text(result),
            }
        )
    else:
        print(client.content_text(result))

    return EXIT_TOOL_ERROR if result.is_error or error_message else EXIT_SUCCESS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="awsdocs",
        description="CLI for the official AWS Knowledge MCP server (AWS docs, Blog, What's New, re:Post).",
    )
    parser.add_argument("--version", action="version", version=f"awsdocs {tool_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_search = subparsers.add_parser(
        "search", help="Search AWS docs / Blog / What's New / re:Post / Agent Skills."
    )
    p_search.add_argument("query")
    p_search.add_argument(
        "--topic",
        action="append",
        choices=SEARCH_TOPICS,
        metavar="TOPIC",
        help=f"Restrict the search domain (repeatable, max {MAX_TOPICS}). One of: {', '.join(SEARCH_TOPICS)}.",
    )
    p_search.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_SEARCH_LIMIT,
        help=f"Number of results (default: {DEFAULT_SEARCH_LIMIT}).",
    )
    add_common_args(p_search)
    p_search.set_defaults(func=cmd_search)

    p_fetch = subparsers.add_parser("fetch", help="Fetch one or more AWS pages as Markdown.")
    p_fetch.add_argument("urls", nargs="+", metavar="url")
    p_fetch.add_argument(
        "--start-index",
        type=int,
        help="Start reading at this char offset (see the char ranges in a truncated page's table of contents).",
    )
    p_fetch.add_argument(
        "--max-length",
        type=int,
        help="Max chars per read (server default: 10000).",
    )
    p_fetch.add_argument(
        "--all",
        action="store_true",
        help="Keep reading while the page is truncated and write the whole page as one file.",
    )
    add_common_args(p_fetch)
    p_fetch.set_defaults(func=cmd_fetch)

    p_regions = subparsers.add_parser("regions", help="List AWS regions (id and name).")
    add_common_args(p_regions)
    p_regions.set_defaults(func=cmd_regions)

    p_avail = subparsers.add_parser(
        "availability",
        help="Check product / API / CloudFormation resource availability per region.",
    )
    p_avail.add_argument("--type", required=True, choices=AVAILABILITY_TYPES)
    p_avail.add_argument(
        "--region",
        action="append",
        required=True,
        help=f"Region code (repeatable, max {MAX_AVAILABILITY_REGIONS}; more than one requires --filter).",
    )
    p_avail.add_argument(
        "--filter",
        action="append",
        help="Exact catalog name (repeatable), e.g. 'AWS Lambda', 'Lambda+Invoke', 'AWS::Lambda::Function'.",
    )
    p_avail.add_argument("--next-token", help="Pagination token (single region, no --filter).")
    add_common_args(p_avail)
    p_avail.set_defaults(func=cmd_availability)

    p_skill = subparsers.add_parser("skill", help="Retrieve an AWS Agent Skill found by search.")
    p_skill.add_argument("skill_name")
    p_skill.add_argument("--file", help="A file inside the skill (default: its SKILL.md body).")
    add_common_args(p_skill)
    p_skill.set_defaults(func=cmd_skill)

    p_tools = subparsers.add_parser(
        "tools", help="List the tools the server currently advertises (not hardcoded)."
    )
    add_common_args(p_tools)
    p_tools.set_defaults(func=cmd_tools)

    p_call = subparsers.add_parser(
        "call", help="Call any tool by name directly (fallback for new/renamed tools)."
    )
    p_call.add_argument(
        "tool_name", help=f"Tool name; the {TOOL_PREFIX} prefix is added if missing."
    )
    p_call.add_argument(
        "--args", help='Tool arguments as a JSON object, e.g. \'{"search_phrase": "..."}\'.'
    )
    p_call.add_argument(
        "--no-prefix", action="store_true", help=f"Don't add the {TOOL_PREFIX} prefix."
    )
    add_common_args(p_call)
    p_call.set_defaults(func=cmd_call)

    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Limits the server would otherwise reject (or silently ignore) -> exit 2."""
    if getattr(args, "topic", None) and len(args.topic) > MAX_TOPICS:
        parser.error(f"--topic accepts at most {MAX_TOPICS} values")
    if getattr(args, "limit", 1) is not None and getattr(args, "limit", 1) < 1:
        parser.error("--limit must be >= 1")
    if args.command == "availability" and len(args.region) > MAX_AVAILABILITY_REGIONS:
        parser.error(f"--region accepts at most {MAX_AVAILABILITY_REGIONS} values")
    if args.command == "fetch":
        if args.start_index is not None and args.start_index < 0:
            parser.error("--start-index must be >= 0")
        if args.max_length is not None and args.max_length < 1:
            parser.error("--max-length must be >= 1")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)

    try:
        return args.func(args)
    except responses.ToolResponseError as exc:
        print(f"Tool error: {exc}", file=sys.stderr)
        return EXIT_TOOL_ERROR
    except responses.EmptyResponseError as exc:
        print(f"Empty response: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    except client.RateLimitError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    except Exception as exc:  # connection/transport failures, unexpected shapes
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
