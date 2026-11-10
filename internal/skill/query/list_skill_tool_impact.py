"""List downstream skills/tools for a changed skill or tools/ CLI.

Reads the shared graph (SKILL.md frontmatter + repo-tools.yaml). Does not
rewrite files and is not wired into lefthook — invoke from the just recipe
when deciding what to open after a change.

Accepts a skill frontmatter name, repo-tools.yaml key, SKILL.md path, or
registered tools/ path. Does not infer a target from git status.
"""

from __future__ import annotations

import argparse
import sys

from skill.util.repo_tools_registry import REPO_ROOT
from skill.util.skill_tool_graph import (
    ImpactHit,
    UnknownTargetError,
    impact_for_target,
    load_graph,
    resolve_target,
)

EPILOG = """\
output:
  must-see  downstream dependency that must be reviewed
  check     related dependency that should be checked
  hop       distance from the changed target in the relation graph

examples:
  just --justfile tools/internal/justfile skill-tool-impact aim
  just --justfile tools/internal/justfile skill-tool-impact \\
    meta-plugins/skills/changing-skills-and-tools/SKILL.md
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill-tool-impact",
        description="List downstream skills and tools for a changed target.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "targets",
        nargs="*",
        metavar="TARGET",
        help=("skill name, repo-tools.yaml key, SKILL.md path, or registered tools/ path"),
    )
    return parser


def format_hits(target_label: str, hits: list[ImpactHit]) -> str:
    lines = [f"target: {target_label}"]
    tools = [hit for hit in hits if hit.kind == "tool"]
    skills = [hit for hit in hits if hit.kind == "skill"]
    if tools:
        lines.append("downstream tools:")
        for hit in tools:
            lines.append(f"  {hit.look}  {hit.name}  {hit.path}  {hit.via}  hop={hit.hop}")
    if skills:
        lines.append("downstream skills:")
        for hit in skills:
            lines.append(f"  {hit.look}  {hit.name}  {hit.path}  {hit.via}  hop={hit.hop}")
    if not tools and not skills:
        lines.append("no downstream skills or tools")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.targets:
        parser.error("at least one TARGET is required")

    graph = load_graph()
    exit_code = 0
    blocks: list[str] = []
    for raw in args.targets:
        try:
            target = resolve_target(raw, graph, REPO_ROOT)
        except UnknownTargetError as exc:
            print(f"error: {exc}", file=sys.stderr)
            exit_code = 1
            continue
        label = f"{target.kind} {target.name}"
        if target.path:
            label = f"{label} ({target.path})"
        hits = impact_for_target(graph, target)
        blocks.append(format_hits(label, hits))

    if blocks:
        print("\n\n".join(blocks))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
