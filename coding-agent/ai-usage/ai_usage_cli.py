r"""CLI entry point for `ai-usage show`: gathers per-tool rate-limit snapshots from
`ai_usage_core.collectors` and renders them as a table (see ai_usage_core/rendering.py).

Claude Code + Codex are always collected. Cline was evaluated and dropped -- see
../.claude/plans/ai-cost-usage-visualization/04-cline-collector-and-cli.md for why
(its `/usages` endpoint returns raw per-call token history, not 5h/weekly/monthly
window percentages). Antigravity is out of scope for the same reason (see
00-overview.md). Cursor has no pull API either, but unlike Cline/Antigravity its
`/usage` slash command can be driven through a real interactive session (see
ai_usage_core/collectors/cursor.py) -- that's slow (tens of seconds, a real
process boot) and returns a raw screen dump rather than parsed percentages, so
it's opt-in via `--cursor` rather than part of the default table.

Each collector is called independently and any exception is caught here so one
tool's failure or absence (e.g. `codex` not installed) never blocks the others
from displaying.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ai_usage_core.collectors import claude_code, codex, cursor
from ai_usage_core.rendering import render_table

_COLLECTORS = (claude_code.collect, codex.collect)


def cmd_show(args: argparse.Namespace) -> int:
    results = []
    for collect in _COLLECTORS:
        try:
            results.append(collect())
        except Exception as exc:
            print(f"warning: collector failed: {exc}", file=sys.stderr)
    print(render_table(results))

    if args.cursor:
        try:
            raw = cursor.collect_raw()
        except Exception as exc:
            print(f"warning: cursor collector failed: {exc}", file=sys.stderr)
            raw = None
        print()
        print("=== cursor (/usage) ===")
        if raw is None:
            print("(unavailable: cursor-agent not found, or pywinpty/pyte not installed)")
        else:
            print(raw)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-usage",
        description="Show AI coding tool usage / rate-limit status in the terminal.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_show = subparsers.add_parser("show", help="Show current usage across all supported tools.")
    p_show.add_argument(
        "--cursor",
        action="store_true",
        help="Also drive `cursor-agent` interactively and dump its /usage screen (slow).",
    )
    p_show.set_defaults(func=cmd_show)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
