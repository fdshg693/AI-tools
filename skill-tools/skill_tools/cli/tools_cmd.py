"""repo-tools.yaml list and install commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import create_source
from ..repo_tools.descriptions import resolve_description
from ..repo_tools.load import (
    install_repo_tools,
    load_repo_tools,
    resolve_install_root,
    select_repo_tools,
)
from ..source import display_skill_path
from .arguments import (
    _add_runtime_arguments,
    _load_runtime_config,
    _source_description,
)


def _add_list_tools_command(commands) -> None:
    parser = commands.add_parser(
        "list-tools",
        help=(
            "list the tools registered in repo-tools.yaml as name, path, install command, "
            "and summary"
        ),
    )
    _add_runtime_arguments(parser)
    parser.add_argument("--json", action="store_true", help="write the tools as JSON")


def _add_install_tools_command(commands) -> None:
    parser = commands.add_parser(
        "install-tools",
        help="run the install command of repo-tools.yaml entries (all tools when none are named)",
    )
    _add_runtime_arguments(parser)
    parser.add_argument(
        "tools",
        nargs="*",
        help="tool names or repo-relative paths from repo-tools.yaml (default: every tool)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show the install commands without running them"
    )


def _command_list_tools(args: argparse.Namespace, cwd: Path) -> int:
    config = _load_runtime_config(args, cwd)
    source = create_source(config)
    rows: list[dict[str, str]] = []
    for tool in load_repo_tools(source):
        rows.append(
            {
                "name": tool.key,
                "path": display_skill_path(tool.path.as_posix(), source.descriptor),
                "install": tool.install,
                "description": resolve_description(tool, source),
            }
        )
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print("\t".join((row["name"], row["path"], row["install"], row["description"])))
    print(f"source: {_source_description(source)}", file=sys.stderr)
    return 0


def _command_install_tools(args: argparse.Namespace, cwd: Path) -> int:
    config = _load_runtime_config(args, cwd)
    source = create_source(config)
    selected = select_repo_tools(load_repo_tools(source), args.tools)
    root = None if args.dry_run else resolve_install_root(source)
    action = "would install" if args.dry_run else "install"
    for tool in selected:
        print(f"{action}\t{tool.key}\t{tool.install}")
    if args.dry_run:
        return 0
    install_repo_tools(selected, root)
    print(f"source: {_source_description(source)}", file=sys.stderr)
    return 0
