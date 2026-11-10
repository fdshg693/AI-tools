"""Top-level `--fb` mode: a small parser that does not share dests with subcommands."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ..config import create_source
from ..feedback import resolve_fb_root, resolve_fb_target, save_feedback
from ..models import SkillToolsError
from .arguments import _add_runtime_arguments, _load_runtime_config

_SUBCOMMANDS = frozenset(
    {
        "list-skills",
        "install-skills",
        "installed-skills",
        "update-skills",
        "remove-skills",
        "list-tools",
        "install-tools",
        "workflow",
        "hooks",
        "search",
        "build-index",
        "config",
        "self-update",
    }
)
_OPTIONS_WITH_VALUE = frozenset(
    {
        "--config",
        "--source",
        "--repo",
        "--github-owner",
        "--github-repo",
        "--github-ref",
        "--index-path",
        "--fb",
        "--fb-kind",
        "--fb-text",
    }
)


def fb_requested(argv: Sequence[str]) -> bool:
    """True when `--fb` appears before any subcommand name."""

    index = 0
    tokens = list(argv)
    while index < len(tokens):
        token = tokens[index]
        if token == "--" or token in _SUBCOMMANDS:
            return False
        if token == "--fb" or token.startswith("--fb="):
            return True
        if token in _OPTIONS_WITH_VALUE:
            index += 2
            continue
        index += 1
    return False


def build_fb_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skill-tools")
    parser.add_argument("--fb", required=True, help="skill name, tool name, or workflow id")
    parser.add_argument(
        "--fb-kind",
        choices=("skill", "tool", "workflow"),
        default=None,
        help="catalog to search; omit to search skills, tools, and workflows",
    )
    parser.add_argument(
        "--fb-text",
        default=None,
        help="feedback body; read stdin when omitted",
    )
    _add_runtime_arguments(parser, index_path=False)
    return parser


def execute_fb(argv: Sequence[str], cwd: Path) -> int:
    args = build_fb_parser().parse_args(list(argv))
    text = read_feedback_text(args.fb_text)
    config = _load_runtime_config(args, cwd)
    target = resolve_fb_target(create_source(config), args.fb, args.fb_kind)
    print(save_feedback(resolve_fb_root(config), target, text))
    return 0


def read_feedback_text(explicit: str | None) -> str:
    """Return `--fb-text`, or stdin when the flag is omitted. Empty text is an error."""

    if explicit is None:
        if sys.stdin.isatty():
            raise SkillToolsError(
                "feedback text is empty; pass --fb-text or pipe the body on stdin"
            )
        explicit = sys.stdin.read()
    if explicit == "":
        raise SkillToolsError("feedback text is empty; pass --fb-text or pipe the body on stdin")
    return explicit
