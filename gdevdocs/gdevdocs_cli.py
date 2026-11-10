"""CLI entry point wrapping the Google Developer Knowledge MCP server.

The server (https://developerknowledge.googleapis.com/mcp) requires an API key
in the ``X-Goog-Api-Key`` header. This module wires argparse to ``gdevdocs_core``:

- ``environment`` resolves the key, endpoint, and output directory.
- ``client``    talks to the MCP server (one session per run).
- ``responses`` turns a CallToolResult into a dict or a typed error.
- ``rendering`` turns one result into a Markdown body with a ``URL:`` line.
- ``output``    writes a numbered folder and an ``index.md`` per call.

``search`` / ``fetch`` / ``answer`` print only the ``index.md`` path.
``tools`` and ``call`` print to stdout and do not write a folder.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gdevdocs_core import client, output, rendering, responses
from gdevdocs_core.config import (
    ANSWER_TOOL,
    DEFAULT_ENDPOINT,
    DEFAULT_TIMEOUT,
    EXIT_EMPTY_RESULT,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    EXIT_TOOL_ERROR,
    EXIT_USAGE_ERROR,
    FETCH_TOOL,
    MAX_FETCH_NAMES,
    SEARCH_TOOL,
)
from gdevdocs_core.environment import (
    ConfigError,
    find_git_root,
    get_endpoint,
    get_missing_api_key_message,
    get_normalized_api_key,
    get_output_dir,
    global_config_path,
    load_config_files,
    require_api_key,
    resolve_setting,
)
from gdevdocs_core.environment import SETTINGS as ENV_SETTINGS

TOOL_DIR = Path(__file__).resolve().parent


def tool_version() -> str:
    data = tomllib.loads((TOOL_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


def _mapping(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _items_or_empty(payload: Any, key: str) -> list[Any]:
    values = _mapping(payload).get(key) or []
    return values if isinstance(values, list) else []


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--endpoint",
        help=f"Override the MCP endpoint (default: layered config, else {DEFAULT_ENDPOINT}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )


def _call(args: argparse.Namespace, api_key: str, tool_name: str, arguments: dict[str, Any]):
    return client.call_tool(
        get_endpoint(args.endpoint),
        api_key,
        args.timeout,
        tool_name,
        arguments,
        retry_rate_limit=client.retries_rate_limit(tool_name),
    )


def _write(label: str, items: list[tuple[str, str]]) -> int:
    if not items:
        print("No results.", file=sys.stderr)
        return EXIT_EMPTY_RESULT
    output.print_index_path(output.write_query_results(label, items))
    return EXIT_SUCCESS


def cmd_search(args: argparse.Namespace, api_key: str) -> int:
    payload = responses.as_payload(_call(args, api_key, SEARCH_TOOL, {"query": args.query}))
    items = [rendering.render_search_item(item) for item in _items_or_empty(payload, "results")]
    return _write(args.query, items)


def cmd_fetch(args: argparse.Namespace, api_key: str) -> int:
    try:
        names = [rendering.document_name(value) for value in args.names]
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE_ERROR
    payload = responses.as_payload(_call(args, api_key, FETCH_TOOL, {"names": names}))
    items = [rendering.render_document(doc) for doc in _items_or_empty(payload, "documents")]
    label = names[0] if len(names) == 1 else f"{names[0]} (+{len(names) - 1} more)"
    return _write(label, items)


def cmd_answer(args: argparse.Namespace, api_key: str) -> int:
    payload = _mapping(
        responses.as_payload(_call(args, api_key, ANSWER_TOOL, {"query": args.query}))
    )
    text = str(payload.get("answerText") or payload.get("answer_text") or "").strip()
    references = payload.get("references") or []
    if not text and not references:
        print("No results.", file=sys.stderr)
        return EXIT_EMPTY_RESULT
    title, content = rendering.render_answer(args.query, payload)
    return _write(args.query, [(title, content)])


def cmd_tools(args: argparse.Namespace, api_key: str) -> int:
    tools = client.list_tools(get_endpoint(args.endpoint), api_key, args.timeout)
    for tool in tools:
        schema = getattr(tool, "input_schema", None)
        if schema is None:
            schema = tool.inputSchema
        if hasattr(schema, "model_dump"):
            schema = schema.model_dump()
        description = tool.description or ""
        print(f"## {tool.name}\n{description}\nSchema: {json.dumps(schema, ensure_ascii=False)}\n")
    return EXIT_SUCCESS


def cmd_call(args: argparse.Namespace, api_key: str) -> int:
    try:
        arguments = json.loads(args.args) if args.args else {}
    except json.JSONDecodeError as exc:
        print(f"--args is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    if not isinstance(arguments, dict):
        print("--args must be a JSON object", file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    result = _call(args, api_key, args.tool_name, arguments)
    print(responses.payload_json(result))
    if getattr(result, "is_error", False):
        return EXIT_TOOL_ERROR
    return EXIT_SUCCESS


def cmd_config(_args: argparse.Namespace) -> int:
    files = load_config_files()
    git_root = find_git_root()
    lines = [
        f"cwd:            {Path.cwd()}",
        f"git root:       {git_root or '(git 管理外)'}",
        f"global config:  {global_config_path()}",
        "loaded files (precedence order):",
        *([f"  [{item.scope}] {item.path}" for item in files] or ["  (なし)"]),
        "settings:",
    ]
    shown = {
        "api_key": "(set)" if get_normalized_api_key() else "(missing)",
        "output_dir": str(get_output_dir()),
        "endpoint": get_endpoint(),
    }
    for key in ENV_SETTINGS:
        setting = resolve_setting(key)
        lines.append(f"  {key} = {shown[key]}  <- {setting.source}")
    print("\n".join(lines))
    return EXIT_SUCCESS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gdevdocs",
        description=(
            "CLI for the Google Developer Knowledge MCP server "
            "(GCP, Workspace, and the rest of that corpus)."
        ),
    )
    parser.add_argument("--version", action="version", version=f"gdevdocs {tool_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_search = subparsers.add_parser(
        "search", help="Search documentation chunks (search_documents)."
    )
    p_search.add_argument("query")
    add_connection_args(p_search)
    p_search.set_defaults(func=cmd_search)

    p_fetch = subparsers.add_parser(
        "fetch",
        help=f"Fetch up to {MAX_FETCH_NAMES} documents by documents/... name or https:// URL.",
    )
    p_fetch.add_argument("names", nargs="+", metavar="name")
    add_connection_args(p_fetch)
    p_fetch.set_defaults(func=cmd_fetch)

    p_answer = subparsers.add_parser(
        "answer",
        help="Ask a conceptual question (answer_query). Not retried on 429.",
    )
    p_answer.add_argument("query")
    add_connection_args(p_answer)
    p_answer.set_defaults(func=cmd_answer)

    p_tools = subparsers.add_parser("tools", help="List the tools the server currently advertises.")
    add_connection_args(p_tools)
    p_tools.set_defaults(func=cmd_tools)

    p_call = subparsers.add_parser("call", help="Call any tool by name. Prints raw JSON.")
    p_call.add_argument("tool_name")
    p_call.add_argument("--args", help="Tool arguments as a JSON object.")
    add_connection_args(p_call)
    p_call.set_defaults(func=cmd_call)

    p_config = subparsers.add_parser(
        "config", help="Show which settings are in effect. No network."
    )
    p_config.set_defaults(func=cmd_config)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "fetch" and len(args.names) > MAX_FETCH_NAMES:
        parser.error(f"fetch accepts at most {MAX_FETCH_NAMES} names")

    try:
        if args.command == "config":
            return cmd_config(args)
        try:
            api_key = require_api_key()
        except ConfigError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_RUNTIME_ERROR
        except ValueError:
            print(get_missing_api_key_message(), file=sys.stderr)
            return EXIT_RUNTIME_ERROR
        return args.func(args, api_key)
    except responses.ToolResponseError as exc:
        print(f"Tool error: {exc}", file=sys.stderr)
        return EXIT_TOOL_ERROR
    except responses.EmptyResponseError as exc:
        print(f"Empty response: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    except client.RateLimitError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    except Exception as exc:
        key = ""
        try:
            key = get_normalized_api_key()
        except ConfigError:
            key = ""
        print(client.public_error(exc, key), file=sys.stderr)
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
