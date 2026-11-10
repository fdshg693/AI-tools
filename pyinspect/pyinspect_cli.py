r"""CLI entry point for ``pyinspect``: fetch one PyPI wheel and write an index.

One command, no subcommands. stdout is the ``index.md`` path only (same
contract as ``mslearn`` / web-lookup). The index is an inventory — name,
status, file tree, recommended paths — not a summary of the library.

Example (after ``uv tool install --editable tools/pyinspect``):

    pyinspect requests
    pyinspect requests==2.32.3
    pyinspect beautifulsoup4 --import --module bs4
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence

from pyinspect_core.config import EXIT_RUNTIME_ERROR, EXIT_USAGE
from pyinspect_core.environment import (
    PYINSPECT_ROOT,
    get_max_bytes,
    get_output_dir,
    load_environment,
)
from pyinspect_core.inspect import run_inspect
from pyinspect_core.pypi import NotFoundError, PyInspectError, UsageError


def tool_version() -> str:
    data = tomllib.loads((PYINSPECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyinspect",
        description=(
            "Download one PyPI wheel (JSON size check first) and write a local "
            "file-tree index. Prints only the index.md path."
        ),
    )
    parser.add_argument("--version", action="version", version=f"pyinspect {tool_version()}")
    parser.add_argument(
        "specifier",
        help="PyPI project name, or NAME==VERSION. extras / URLs / ranges are rejected.",
    )
    parser.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help=(
            "Also install the selected wheel into an ephemeral venv (no deps) "
            "and list public names. Off by default."
        ),
    )
    parser.add_argument(
        "--module",
        help="Import name when inference from top_level.txt is empty or ambiguous. Requires --import.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    load_environment()
    try:
        max_bytes = get_max_bytes()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    try:
        outcome = run_inspect(
            args.specifier,
            do_import=args.do_import,
            module=args.module,
            output_dir=get_output_dir(),
            max_bytes=max_bytes,
        )
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    except NotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except PyInspectError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR

    if outcome.index_path is not None:
        print(outcome.index_path.as_posix())
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
