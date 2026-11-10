"""Single pre-commit entry for the tools/internal Python jobs.

lefthook used to start one `just` -> `powershell` -> `uv run python` chain per
job (~1s of process startup each, ~15 jobs). This runs the same modules
in-process instead, in a fixed dependency order:

    fix   — SKILL.md meta defaults -> generated catalogs/marketplaces -> tool
            manifest version bumps (all write files; lefthook re-stages them)
    check — read-only checks (SKILL.md version bump, repo-tools consistency)

Each task still runs only when a staged path matches its globs (the same globs
lefthook used per job). `--all` ignores the staged list and runs every task,
e.g. for a manual regeneration outside a commit.

Run via `just --justfile tools/internal/justfile precommit-fix|precommit-check`.
"""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Task:
    name: str
    module: str
    globs: tuple[str, ...]
    # Tasks whose outputs this one reads: if any of them ran, this one runs too.
    after: tuple[str, ...] = ()
    # How to call the module's main(): "none" -> main(), "argv" -> main([module]),
    # "list" -> main([]) (argparse mains that would otherwise read sys.argv).
    call: str = "none"


SKILL_MD = ("**/SKILL.md",)

FIX_TASKS = (
    # SKILL.md meta defaults first: the catalog generators below read the frontmatter.
    Task("skill-versions", "skill.set.set_skill_versions", SKILL_MD),
    Task("skill-descriptions", "skill.set.set_skill_descriptions", SKILL_MD),
    Task("skill-tags", "skill.set.set_skill_tags", SKILL_MD),
    Task(
        "marketplace",
        "plugin_meta.generate.generate_marketplace",
        ("**/.claude-plugin/plugin.json", "ai-tools.yaml"),
    ),
    Task(
        "codex-marketplace",
        "plugin_meta.generate.generate_codex_marketplace",
        ("**/.codex-plugin/plugin.json", "ai-tools.yaml"),
    ),
    Task(
        "copilot-marketplace",
        "plugin_meta.generate.generate_copilot_marketplace",
        ("copilot-plugins/meta/**/SKILL.md", "ai-tools.yaml"),
    ),
    Task(
        "skill-catalog",
        "plugin_meta.generate.generate_skill_catalog",
        ("**/skills/**", ".claude-plugin/marketplace.json", "ai-tools.yaml"),
        after=("marketplace",),
    ),
    Task(
        "skills-catalog-md",
        "plugin_meta.generate.generate_skills_catalog_md",
        ("**/skills/**", "ai-tools.yaml"),
    ),
    Task(
        "readme-tools-section",
        "plugin_meta.generate.generate_readme_tools_section",
        ("ai-tools.yaml",),
    ),
    Task("tool-version-bump", "release.bump_tool_versions", ("tools/**",), call="list"),
)

CHECK_TASKS = (
    Task(
        "skill-version-bump-check",
        "skill.check.check_skill_version_bump",
        SKILL_MD,
        call="argv",
    ),
    Task(
        "skill-repo-tools-check",
        "skill.check.check_skill_repo_tools",
        ("**/SKILL.md", "repo-tools.yaml", "tools/**/pyproject.toml", "tools/**/package.json"),
        call="argv",
    ),
    Task(
        "repo-tool-relations-check",
        "skill.check.check_repo_tool_relations",
        ("**/SKILL.md", "repo-tools.yaml", "tools/**/pyproject.toml", "tools/**/package.json"),
        call="argv",
    ),
)

PHASES = {"fix": FIX_TASKS, "check": CHECK_TASKS}


def staged_files() -> list[PurePosixPath]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--cached", "--diff-filter=ACMR"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        raise SystemExit(result.returncode)
    return [PurePosixPath(line) for line in result.stdout.splitlines() if line.strip()]


def matches(task: Task, paths: list[PurePosixPath]) -> bool:
    return any(path.full_match(glob) for path in paths for glob in task.globs)


def select(tasks: tuple[Task, ...], paths: list[PurePosixPath] | None) -> list[Task]:
    if paths is None:
        return list(tasks)
    selected: list[Task] = []
    names: set[str] = set()
    for task in tasks:
        if matches(task, paths) or names.intersection(task.after):
            selected.append(task)
            names.add(task.name)
    return selected


def invoke(task: Task) -> int:
    main: Callable[..., int | None] = importlib.import_module(task.module).main
    try:
        if task.call == "argv":
            result = main([task.module])
        elif task.call == "list":
            result = main([])
        else:
            result = main()
    except SystemExit as exc:
        if exc.code is None or exc.code == 0:
            return 0
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 1
        return int(exc.code)
    return result or 0


def run(tasks: list[Task]) -> int:
    failed: list[str] = []
    for task in tasks:
        started = time.perf_counter()
        code = invoke(task)
        elapsed = time.perf_counter() - started
        status = "ok" if code == 0 else f"FAILED ({code})"
        print(f"[precommit] {task.name}: {status} in {elapsed:.2f}s", flush=True)
        if code != 0:
            failed.append(task.name)
    if failed:
        print(f"[precommit] failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phase", choices=sorted(PHASES))
    parser.add_argument(
        "--all", action="store_true", help="run every task regardless of staged files"
    )
    args = parser.parse_args(argv)
    paths = None if args.all else staged_files()
    return run(select(PHASES[args.phase], paths))


if __name__ == "__main__":
    sys.exit(main())
