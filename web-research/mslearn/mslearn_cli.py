r"""CLI entry point wrapping the official Microsoft Learn MCP server.

The server (https://learn.microsoft.com/api/mcp) needs no auth and exposes three
tools as of this writing: ``microsoft_docs_search``, ``microsoft_docs_fetch``,
``microsoft_code_sample_search``. This module only wires argparse subcommands to
the building blocks in ``mslearn_core``:

- ``mslearn_core.client``    talks to the MCP server (fastmcp.Client).
- ``mslearn_core.rendering`` turns one raw result item into a (category, title,
  markdown) triple.
- ``mslearn_core.output``    writes those triples into one numbered folder per
  call (Q&A results under a `qa/` subfolder) with an `index.md` summary, and
  prints only the `index.md` path.

``search`` / ``code-search`` / ``fetch`` all write every result under a fresh
``NNNN-<slug>/`` folder inside ``MSLEARN_MCP_OUTPUT_DIR`` and print only the
``index.md`` path back -- never per-file paths or content -- so a caller's
context isn't spent on page bodies it didn't ask to see yet. Each line in
``index.md`` carries its file's char count, so a caller can pick which
results to Read by title and, among those, route only the large ones through
`aim --parallel` instead (see the `ms-digest` skill) -- there is no whole-run
aggregate, since that number isn't actionable on its own. ``--json``
switches to a single JSON object on stdout with the full content inline and
skips file writing entirely, for piping into `jq` or another CLI.

Example (after installing the `mslearn` console script -- see README.md):
    mslearn search "Azure Functions timeout"
    mslearn fetch https://learn.microsoft.com/azure/azure-functions/functions-versions
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent

from mslearn_core import client, rendering
from mslearn_core.config import (
    DEFAULT_ENDPOINT,
    DEFAULT_TIMEOUT,
    ENDPOINT_ENV,
    EXIT_EMPTY_RESULT,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    EXIT_TOOL_ERROR,
)
from mslearn_core.output import print_index_path, write_query_results


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


def cmd_search(args: argparse.Namespace) -> int:
    endpoint = client.resolve_endpoint(args.endpoint, args.max_token_budget)
    result = client.call_tool(
        endpoint, args.timeout, "microsoft_docs_search", {"query": args.query}
    )
    if result.is_error:
        print(f"microsoft_docs_search failed: {client.content_text(result)}", file=sys.stderr)
        return EXIT_TOOL_ERROR

    results = (result.structured_content or {}).get("results", [])
    if not results:
        print("No results.", file=sys.stderr)
        return EXIT_EMPTY_RESULT

    if args.json:
        print(json.dumps({"query": args.query, "results": results}, ensure_ascii=False, indent=2))
        return EXIT_SUCCESS

    index_path = write_query_results(
        args.query, [rendering.render_search_item(item) for item in results]
    )
    print_index_path(index_path)
    return EXIT_SUCCESS


def cmd_code_search(args: argparse.Namespace) -> int:
    endpoint = client.resolve_endpoint(args.endpoint, args.max_token_budget)
    arguments: dict[str, Any] = {"query": args.query}
    if args.language:
        arguments["language"] = args.language

    result = client.call_tool(endpoint, args.timeout, "microsoft_code_sample_search", arguments)
    if result.is_error:
        print(
            f"microsoft_code_sample_search failed: {client.content_text(result)}", file=sys.stderr
        )
        return EXIT_TOOL_ERROR

    results = (result.structured_content or {}).get("results", [])
    if not results:
        print("No results.", file=sys.stderr)
        return EXIT_EMPTY_RESULT

    if args.json:
        print(
            json.dumps(
                {"query": args.query, "language": args.language, "results": results},
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_SUCCESS

    index_path = write_query_results(
        args.query, [rendering.render_code_item(item) for item in results]
    )
    print_index_path(index_path)
    return EXIT_SUCCESS


def cmd_fetch(args: argparse.Namespace) -> int:
    endpoint = client.resolve_endpoint(args.endpoint)
    result = client.call_tool(endpoint, args.timeout, "microsoft_docs_fetch", {"url": args.url})
    if result.is_error:
        print(f"microsoft_docs_fetch failed: {client.content_text(result)}", file=sys.stderr)
        return EXIT_TOOL_ERROR

    markdown = client.content_text(result)
    if not markdown.strip():
        print(f"Fetched empty content from {args.url}", file=sys.stderr)
        return EXIT_EMPTY_RESULT

    if args.json:
        print(json.dumps({"url": args.url, "content": markdown}, ensure_ascii=False))
        return EXIT_SUCCESS

    index_path = write_query_results(args.url, [rendering.render_fetch_item(args.url, markdown)])
    print_index_path(index_path)
    return EXIT_SUCCESS


def cmd_tools(args: argparse.Namespace) -> int:
    endpoint = client.resolve_endpoint(args.endpoint)
    tools = client.list_tools(endpoint, args.timeout)

    if args.json:
        print(json.dumps([t.model_dump(mode="json") for t in tools], ensure_ascii=False, indent=2))
        return EXIT_SUCCESS

    for tool in tools:
        print(
            f"## {tool.name}\n{tool.description or ''}\nSchema: {json.dumps(tool.inputSchema, ensure_ascii=False)}\n"
        )
    return EXIT_SUCCESS


def cmd_call(args: argparse.Namespace) -> int:
    endpoint = client.resolve_endpoint(args.endpoint)
    try:
        arguments = json.loads(args.args) if args.args else {}
    except json.JSONDecodeError as exc:
        print(f"--args is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR

    result = client.call_tool(endpoint, args.timeout, args.tool_name, arguments)

    if args.json:
        print(
            json.dumps(
                {
                    "is_error": result.is_error,
                    "structured_content": result.structured_content,
                    "content_text": client.content_text(result),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(client.content_text(result))

    return EXIT_TOOL_ERROR if result.is_error else EXIT_SUCCESS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mslearn",
        description="CLI for the official Microsoft Learn MCP server.",
    )
    parser.add_argument("--version", action="version", version=f"mslearn {tool_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_search = subparsers.add_parser("search", help="Semantic search over Microsoft/Azure docs.")
    p_search.add_argument("query")
    p_search.add_argument(
        "--max-token-budget",
        type=int,
        help="Cap search-result token size (server-side; see maxTokenBudget in the MCP docs).",
    )
    add_common_args(p_search)
    p_search.set_defaults(func=cmd_search)

    p_code = subparsers.add_parser(
        "code-search", help="Search official Microsoft/Azure code samples."
    )
    p_code.add_argument("query")
    p_code.add_argument(
        "--language", help="Restrict to one language, e.g. python, csharp, typescript."
    )
    p_code.add_argument(
        "--max-token-budget", type=int, help="Cap search-result token size (server-side)."
    )
    add_common_args(p_code)
    p_code.set_defaults(func=cmd_code_search)

    p_fetch = subparsers.add_parser("fetch", help="Fetch one Learn page as Markdown.")
    p_fetch.add_argument("url")
    add_common_args(p_fetch)
    p_fetch.set_defaults(func=cmd_fetch)

    p_tools = subparsers.add_parser(
        "tools", help="List the tools the server currently advertises (not hardcoded)."
    )
    add_common_args(p_tools)
    p_tools.set_defaults(func=cmd_tools)

    p_call = subparsers.add_parser(
        "call", help="Call any tool by name directly (fallback for new/renamed tools)."
    )
    p_call.add_argument("tool_name")
    p_call.add_argument(
        "--args", help='Tool arguments as a JSON object, e.g. \'{"query": "..."}\'.'
    )
    add_common_args(p_call)
    p_call.set_defaults(func=cmd_call)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except Exception as exc:  # connection/transport failures, ToolError, unexpected shapes
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
