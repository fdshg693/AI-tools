"""agents-rules: generate per-tool rule files from nested AGENTS.md files."""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from .generate import (
    GenerateError,
    configured_output_dir,
    discover_agents,
    find_repo_root,
    plan,
    write,
)
from .targets import ALL_TARGETS, TARGETS

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def tool_version() -> str:
    data = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agents-rules",
        description=(
            "リポジトリ各所の AGENTS.md から、Cline / GitHub Copilot / Antigravity / Cursor "
            "向けのディレクトリスコープ付きルールファイルを生成する。"
        ),
    )
    parser.add_argument("--version", action="version", version=f"agents-rules {tool_version()}")
    parser.add_argument(
        "-t",
        "--target",
        action="append",
        choices=[*TARGETS, "all"],
        help=(
            "生成対象（複数指定可）。all は "
            f"{', '.join(ALL_TARGETS)}（cursor は含まない）。既定: all"
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="走査するリポジトリルート（既定: cwd から親へ .git、次に ai-tools.yaml を探す）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "出力先ディレクトリ（--target を1つだけ指定したときのみ）。"
            "既定: ai-tools.yaml の output_dir、無ければ各ツールの標準位置"
        ),
    )
    parser.add_argument(
        "-x",
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="走査から除外するディレクトリ（リポジトリルート相対の glob、複数指定可）",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-n", "--dry-run", action="store_true", help="書き込まず、生成予定と差分有無を表示する"
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="書き込まず、生成物が最新でなければ終了コード1で終える（CI 向け）",
    )
    mode.add_argument(
        "--list-sources", action="store_true", help="対象になる AGENTS.md の一覧だけを表示する"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="ファイルごとの出力を省く")
    return parser


def resolve_targets(values: list[str] | None) -> list[str]:
    selected: list[str] = []
    for value in values or ["all"]:
        for name in ALL_TARGETS if value == "all" else (value,):
            if name not in selected:
                selected.append(name)
    return selected


def run(args: argparse.Namespace) -> int:
    target_names = resolve_targets(args.target)
    if args.output_dir is not None and len(target_names) != 1:
        raise GenerateError("--output-dir は --target を1つだけ指定したときに使えます。")

    repo_root = (args.repo_root or find_repo_root(Path.cwd())).resolve()
    if not repo_root.is_dir():
        raise GenerateError(f"--repo-root {repo_root} はディレクトリではありません。")
    agents = discover_agents(repo_root, args.exclude)

    if args.list_sources:
        for agent_path in agents:
            print(agent_path.relative_to(repo_root).as_posix())
        return 0

    stale = 0
    for name in target_names:
        target = TARGETS[name]
        output_dir = (
            args.output_dir or repo_root / configured_output_dir(repo_root, target)
        ).resolve()
        counts = {"new": 0, "changed": 0, "unchanged": 0}
        for item in plan(repo_root, output_dir, target, agents):
            status = item.status
            counts[status] += 1
            if status != "unchanged" and not (args.dry_run or args.check):
                write(item)
            if not args.quiet and (status != "unchanged" or args.dry_run):
                print(f"[{name}] {status:9} {_display(item.target_path, repo_root)}")
        pending = counts["new"] + counts["changed"]
        stale += pending
        verb = "would update" if (args.dry_run or args.check) else "updated"
        print(
            f"{target.label}: {len(agents)} sources, {verb} {pending} "
            f"(new {counts['new']}, changed {counts['changed']}) in "
            f"{_display(output_dir, repo_root)}"
        )

    if args.check and stale:
        print(f"{stale} generated file(s) are out of date.", file=sys.stderr)
        return 1
    return 0


def _display(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except GenerateError as error:
        print(f"agents-rules: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
