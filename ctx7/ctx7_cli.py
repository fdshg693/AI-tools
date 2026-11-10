r"""CLI entry point for the Context7 REST API (v2), hit directly with ``requests``.

Two subcommands map 1:1 onto the two endpoints this package wraps
(``ctx7_core.client``):

    ctx7 library <name> "<query>"    -> GET /api/v2/libs/search
    ctx7 docs <library-id> "<query>" -> GET /api/v2/context

No MCP client, no ``fastmcp`` dependency -- unlike ``tools/mslearn``, this
talks the Context7 REST API directly, the same "SDK/API directly + ``.env``
for credentials" shape as ``tools/tav-cli``. It differs from ``tav-cli`` in
one deliberate way: there is no ``--topic``/file-writing layer. Both
endpoints' responses are small (5-7KB observed against the live API) so
results always print straight to stdout; a folder-of-files layout would just
add indirection for no benefit at this size.

``--json`` prints a self-describing envelope (``{"command", "exit_code",
"result"}``) for piping into ``jq`` etc.; without it, prints a short
human-readable rendering (``library``) or the raw response body (``docs``).

Example (after installing the ``ctx7`` console script -- see README.md):
    ctx7 library react "react hooks" --json
    ctx7 docs /react/react "useEffect cleanup" --json
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Sequence
from typing import Any

from ctx7_core.client import DEFAULT_TIMEOUT, Context7ApiError, get_context, search_libraries
from ctx7_core.environment import CTX7_ROOT, get_normalized_api_key, load_environment
from ctx7_core.result_contract import (
    EXIT_API_ERROR,
    EXIT_EMPTY_RESULT,
    EXIT_INCOMPLETE,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
)


def tool_version() -> str:
    data = tomllib.loads((CTX7_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a self-describing JSON envelope ({command, exit_code, result}) to stdout "
        "instead of a plain-text rendering.",
    )
    parser.add_argument(
        "--fast", action="store_true", help="Skip Context7's LLM re-ranking (fast=true)."
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    parser.add_argument(
        "--api-key",
        help="Override CONTEXT7_API_KEY for this call. Optional -- Context7 answers "
        "unauthenticated requests too, just at a lower rate limit (see README).",
    )


def resolve_api_key(args: argparse.Namespace) -> str | None:
    api_key = (args.api_key or "").strip()
    if api_key:
        return api_key
    load_environment()
    return get_normalized_api_key() or None


def build_envelope(command: str, exit_code: int, result: Any) -> dict[str, Any]:
    return {"command": command, "exit_code": exit_code, "result": result}


def _print_json(command: str, exit_code: int, result: Any) -> None:
    print(json.dumps(build_envelope(command, exit_code, result), ensure_ascii=False, indent=2))


def cmd_library(args: argparse.Namespace) -> int:
    api_key = resolve_api_key(args)
    try:
        result = search_libraries(
            args.name, args.query, fast=args.fast, api_key=api_key, timeout=args.timeout
        )
    except Context7ApiError as exc:
        return _emit_api_error(args, "library", exc)

    results = (result.data or {}).get("results", [])
    if not results:
        if args.json:
            _print_json("library", EXIT_EMPTY_RESULT, result.data)
        else:
            print("No matching libraries.", file=sys.stderr)
        return EXIT_EMPTY_RESULT

    if args.json:
        _print_json("library", EXIT_SUCCESS, result.data)
    else:
        render_library_results(result.data)
    return EXIT_SUCCESS


def render_library_results(data: dict[str, Any]) -> None:
    for item in data.get("results", []):
        print(f"{item.get('id')}  {item.get('title')}")
        description = item.get("description")
        if description:
            print(f"  {description}")
        print(
            f"  trustScore={item.get('trustScore')} snippets={item.get('totalSnippets')} "
            f"stars={item.get('stars')} state={item.get('state')}"
        )
        print()


def cmd_docs(args: argparse.Namespace) -> int:
    api_key = resolve_api_key(args)
    try:
        result = get_context(
            args.library_id,
            args.query,
            type_=args.type,
            fast=args.fast,
            api_key=api_key,
            timeout=args.timeout,
        )
    except Context7ApiError as exc:
        return _emit_api_error(args, "docs", exc)

    if result.status_code == 202:
        if args.json:
            _print_json("docs", EXIT_INCOMPLETE, result.data)
        else:
            print("Library is still being indexed by Context7; try again shortly.", file=sys.stderr)
        return EXIT_INCOMPLETE

    if args.json:
        _print_json("docs", EXIT_SUCCESS, result.data)
    elif isinstance(result.data, str):
        print(result.data)
    else:
        print(json.dumps(result.data, ensure_ascii=False, indent=2))
    return EXIT_SUCCESS


def _emit_api_error(args: argparse.Namespace, command: str, exc: Context7ApiError) -> int:
    if args.json:
        _print_json(command, EXIT_API_ERROR, exc.payload)
    else:
        detail = exc.payload.get("message") or exc.payload.get("error")
        print(f"Context7 API error ({exc.status_code}): {detail}", file=sys.stderr)
    return EXIT_API_ERROR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ctx7",
        description="Thin CLI over the Context7 REST API (v2): library search + doc-context retrieval.",
    )
    parser.add_argument("--version", action="version", version=f"ctx7 {tool_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_library = subparsers.add_parser(
        "library", help="Search Context7 for candidate library IDs (GET /api/v2/libs/search)."
    )
    p_library.add_argument("name", help="Library/framework name (libraryName).")
    p_library.add_argument(
        "query", help="What you want to do with the library, used to rank candidates."
    )
    add_common_args(p_library)
    p_library.set_defaults(func=cmd_library)

    p_docs = subparsers.add_parser(
        "docs", help="Fetch documentation context for one library ID (GET /api/v2/context)."
    )
    p_docs.add_argument(
        "library_id", help="Context7 library ID, e.g. /react/react or /vercel/next.js/v14.0.0."
    )
    p_docs.add_argument("query", help="Single focused question/topic.")
    p_docs.add_argument(
        "--type", choices=["json", "txt"], default="txt", help="Response format (default: txt)."
    )
    add_common_args(p_docs)
    p_docs.set_defaults(func=cmd_docs)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except Exception as exc:  # connection failures, timeouts, or any other unexpected error
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
