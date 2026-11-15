r"""CLI entry point wrapping the grep.app MCP server.

The server (https://mcp.grep.app) needs no auth and exposes one tool as of this
writing: ``searchGitHub`` (real-world code examples from 1M+ public GitHub
repos). This module only wires argparse subcommands to the building blocks in
``grepapp_core``:

- ``grepapp_core.client``    talks to the MCP server (fastmcp.Client).
- ``grepapp_core.rendering`` turns one raw TextContent block into a (category,
  title, markdown) triple.
- ``grepapp_core.output``    writes those triples into one numbered folder per
  call with an `index.md` summary, and prints only the `index.md` path.

``search`` writes every result under a fresh ``NNNN-<slug>/`` folder inside
``GREPAPP_MCP_OUTPUT_DIR`` and prints only the ``index.md`` path back -- never
per-file paths or content -- so a caller's context isn't spent on match bodies
it didn't ask to see yet. Each line in ``index.md`` carries its file's char
count, so a caller can pick which results to Read by title. ``--json``
switches to a single JSON object on stdout with the full content inline and
skips file writing entirely, for piping into `jq` or another CLI.

Example (after installing the `grepapp` console script -- see README.md):
    grepapp search "useState(" --language TypeScript
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

from grepapp_core import client, rendering
from grepapp_core.config import (
    DEFAULT_ENDPOINT,
    DEFAULT_TIMEOUT,
    ENDPOINT_ENV,
    EXIT_EMPTY_RESULT,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    EXIT_TOOL_ERROR,
)
from grepapp_core.output import print_index_path, write_query_results


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
    endpoint = client.resolve_endpoint(args.endpoint)
    arguments: dict[str, Any] = {"query": args.query}
    if args.language:
        arguments["language"] = args.language
    if args.repo:
        arguments["repo"] = args.repo
    if args.path:
        arguments["path"] = args.path
    if args.match_case:
        arguments["matchCase"] = True
    if args.match_whole_words:
        arguments["matchWholeWords"] = True
    if args.use_regexp:
        arguments["useRegexp"] = True

    result = client.call_tool(endpoint, args.timeout, "searchGitHub", arguments)
    if result.is_error:
        print(f"searchGitHub failed: {client.content_text(result)}", file=sys.stderr)
        return EXIT_TOOL_ERROR

    if rendering.is_empty_response(result.content):
        print("No results.", file=sys.stderr)
        return EXIT_EMPTY_RESULT

    if args.json:
        blocks = [block.text for block in result.content if hasattr(block, "text")]
        print(json.dumps({"query": args.query, "results": blocks}, ensure_ascii=False, indent=2))
        return EXIT_SUCCESS

    items = [
        rendering.render_match_item(position, block.text)
        for position, block in enumerate(result.content, start=1)
    ]
    index_path = write_query_results(args.query, items)
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
        prog="grepapp",
        description="CLI for the grep.app MCP server (real-world code search over 1M+ public GitHub repos).",
    )
    parser.add_argument("--version", action="version", version=f"grepapp {tool_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_search = subparsers.add_parser(
        "search", help="Search public GitHub repos for a literal code pattern."
    )
    p_search.add_argument(
        "query", help="A literal code pattern, e.g. 'useState(' -- not a keyword."
    )
    p_search.add_argument(
        "--language",
        action="append",
        help="Restrict to a language, e.g. TypeScript. Repeat to allow several.",
    )
    p_search.add_argument(
        "--repo", help="Restrict to a repo, e.g. 'facebook/react' (partial match ok)."
    )
    p_search.add_argument(
        "--path", help="Restrict to a file path, e.g. '/route.ts' (partial match ok)."
    )
    p_search.add_argument("--match-case", action="store_true", help="Case-sensitive match.")
    p_search.add_argument(
        "--match-whole-words", action="store_true", help="Match whole words only."
    )
    p_search.add_argument(
        "--use-regexp", action="store_true", help="Treat query as a regular expression."
    )
    add_common_args(p_search)
    p_search.set_defaults(func=cmd_search)

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
