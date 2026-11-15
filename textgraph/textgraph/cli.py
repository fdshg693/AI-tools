from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from .config import Config, ConfigError, load_config
from .check import (
    EXTERNAL,
    BaselineError,
    Finding,
    apply_findings,
    compare_baseline,
    find_broken_links,
    findings_to_json,
    load_baseline,
    preview_hunks,
)
from .query import (
    ImpactResult,
    collapse_paths,
    filter_paths,
    impact_for,
    impact_json,
    is_index_stale,
    resolve_target,
)
from .scan import GitError, SyncStats, find_repo_root, sync_index
from .store import INDEX_DIR, GraphStore, db_path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


class CliError(RuntimeError):
    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def tool_version() -> str:
    data = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


def maybe_print_version(argv: Sequence[str] | None) -> bool:
    raw = list(argv if argv is not None else sys.argv[1:])
    if raw == ["--version"]:
        print(f"textgraph {tool_version()}")
        return True
    return False


def main(argv: Sequence[str] | None = None) -> int:
    if maybe_print_version(argv):
        return 0
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command is None:
        parser.print_help()
        return 2
    try:
        root = _resolve_root(args.path)
        config = load_config(root)
        if args.command == "init":
            return _cmd_init(root, config)
        if args.command == "sync":
            return _cmd_sync(root, config, force=args.force)
        if args.command == "status":
            return _cmd_status(root, config)
        if args.command == "files":
            return _cmd_files(
                root,
                config,
                prefix=args.filter,
                max_depth=args.max_depth,
                as_json=args.json,
            )
        if args.command == "impact":
            return _cmd_impact(root, config, args.target, as_json=args.json)
        if args.command == "check":
            return _cmd_check(
                root,
                config,
                scripts=args.scripts,
                external=args.external,
                as_json=args.json,
                baseline=args.baseline,
            )
        if args.command == "fix":
            return _cmd_fix(
                root, config, apply=args.apply, scripts=args.scripts, external=args.external
            )
    except (ConfigError, BaselineError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    except GitError as exc:
        print(str(exc), file=sys.stderr)
        return 2 if args.command in {"check", "fix"} else 1
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="textgraph",
        description="Index local file links in text files",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="repository root (default: walk from cwd looking for .git)",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="create .textgraph/ and build the first index")
    sync = sub.add_parser("sync", help="update the index for changed files")
    sync.add_argument(
        "--force",
        action="store_true",
        help="re-extract every text file even if the hash is unchanged",
    )
    sub.add_parser("status", help="show file/link counts and last sync time")
    files = sub.add_parser("files", help="list indexed text files")
    files.add_argument(
        "--max-depth",
        type=int,
        default=None,
        metavar="N",
        help="collapse the human tree after N path components (JSON stays flat)",
    )
    files.add_argument(
        "--filter",
        default=None,
        metavar="PREFIX",
        help="keep paths with this string prefix",
    )
    files.add_argument("--json", action="store_true", help="write matching paths as a JSON array")
    impact = sub.add_parser(
        "impact",
        help="show inbound and outbound links for one indexed file",
    )
    impact.add_argument(
        "target",
        help="repository-relative path, absolute path, or basename",
    )
    impact.add_argument("--json", action="store_true", help="write inbound/outbound as JSON")
    check = sub.add_parser("check", help="report broken outbound links")
    _add_scripts_flag(check)
    check.add_argument(
        "--json",
        action="store_true",
        help='write {"findings": [...], "external": N} as JSON',
    )
    check.add_argument(
        "--baseline",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "compare with an earlier `check --json` output and list only new findings "
            "(key: source, raw, status; renamed sources follow git renames)"
        ),
    )
    fix = sub.add_parser(
        "fix",
        help="rewrite unique broken links (dry-run unless --apply)",
    )
    fix.add_argument(
        "--apply",
        action="store_true",
        help="write unique-suffix and git-rename replacements (not git-rename-basename)",
    )
    _add_scripts_flag(fix)
    return parser


def _add_scripts_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scripts",
        action="store_true",
        help=(
            "also scan script files for the same local-link syntax (no comment-vs-code detection)"
        ),
    )
    parser.add_argument(
        "--external",
        action="store_true",
        help=(
            "also list links outside the index that exist on disk "
            "(status external; never counted in the exit code)"
        ),
    )


def _resolve_root(path: Path | None) -> Path:
    if path is not None:
        root = path.expanduser().resolve()
        if not (root / ".git").exists():
            raise CliError(f"not a git repository: {root}")
        return root
    found = find_repo_root(Path.cwd())
    if found is None:
        raise CliError("not a git repository (no .git in cwd or parents)")
    return found


def _cmd_init(root: Path, config: Config) -> int:
    index = root / INDEX_DIR
    if index.exists():
        print("index already exists; run `textgraph sync`", file=sys.stderr)
        return 1
    index.mkdir()
    _print_sync_stats(sync_index(root, force=True, config=config))
    return 0


def _cmd_sync(root: Path, config: Config, *, force: bool) -> int:
    if not (root / INDEX_DIR).exists():
        print("index not found; run `textgraph init`", file=sys.stderr)
        return 1
    _print_sync_stats(sync_index(root, force=force, config=config))
    return 0


def _print_sync_stats(stats: SyncStats) -> None:
    print(f"updated {stats.updated}, skipped {stats.skipped}, removed {stats.removed}")


def _cmd_status(root: Path, config: Config) -> int:
    store = _open_store(root)
    try:
        files, links, unresolved = store.counts()
        last = store.last_sync() or ""
        print(f"files: {files}")
        print(f"links: {links}")
        print(f"unresolved: {unresolved}")
        print(f"last_sync: {last}")
        if config.path is None:
            print("config: (none)")
        else:
            print(f"config: {config.path}")
            print(f"exclude: {len(config.exclude)}")
            print(f"scripts_exclude: {len(config.scripts_exclude)}")
        return 0
    finally:
        store.close()


def _cmd_files(
    root: Path,
    config: Config,
    *,
    prefix: str | None,
    max_depth: int | None,
    as_json: bool,
) -> int:
    if max_depth is not None and max_depth < 1:
        raise CliError("--max-depth must be >= 1")
    store = _open_store(root)
    try:
        _require_fresh(root, store, config)
        paths = filter_paths(store.list_files(), prefix)
        if as_json:
            print(json.dumps(paths, indent=2))
            return 0
        _print_table(("path",), [[path] for path in collapse_paths(paths, max_depth)])
        return 0
    finally:
        store.close()


def _split_external(
    findings: Sequence[Finding], *, show_external: bool
) -> tuple[list[Finding], list[Finding]]:
    """Return (findings to list, real problems) and report hidden externals."""
    problems = [finding for finding in findings if finding.status != EXTERNAL]
    external = len(findings) - len(problems)
    if show_external:
        return list(findings), problems
    if external:
        print(
            f"{external} links point outside the index (exist on disk); use --external to list",
            file=sys.stderr,
        )
    return problems, problems


def _cmd_check(
    root: Path,
    config: Config,
    *,
    scripts: bool,
    external: bool,
    as_json: bool = False,
    baseline: Path | None = None,
) -> int:
    # Read the baseline first so a broken file fails before the scan.
    baseline_keys = load_baseline(baseline) if baseline is not None else None
    store = _open_store(root, code=2)
    try:
        _require_fresh(root, store, config, code=2)
        findings = find_broken_links(root, store, scripts=scripts, config=config)
        external_count = sum(1 for finding in findings if finding.status == EXTERNAL)
        listed, problems = _split_external(findings, show_external=external)
        if baseline_keys is not None:
            # Hidden externals are on neither side, so they are never "resolved".
            if not external:
                baseline_keys = [key for key in baseline_keys if key[2] != EXTERNAL]
            diff = compare_baseline(root, listed, baseline_keys)
            listed = list(diff.new)
            problems = [finding for finding in listed if finding.status != EXTERNAL]
            print(f"{diff.resolved} findings resolved since the baseline", file=sys.stderr)
        if as_json:
            print(json.dumps(findings_to_json(listed, external=external_count), indent=2))
        else:
            _print_findings(listed)
        return 0 if not problems else 1
    finally:
        store.close()


def _cmd_fix(root: Path, config: Config, *, apply: bool, scripts: bool, external: bool) -> int:
    store = _open_store(root, code=2)
    try:
        _require_fresh(root, store, config, code=2)
        findings, problems = _split_external(
            find_broken_links(root, store, scripts=scripts, config=config),
            show_external=external,
        )
        applyable = [finding for finding in findings if finding.applyable]
        skipped = [finding for finding in findings if not finding.applyable]
        hunks = preview_hunks(root, applyable)
        if apply:
            failed = apply_findings(root, applyable)
            skipped.extend(failed)
            if hunks:
                print("applied")
                print("\n".join(hunks))
            elif not findings:
                print("(none)")
        else:
            if hunks:
                print("would apply")
                print("\n".join(hunks))
            elif not findings:
                print("(none)")
        remaining = skipped
        if remaining:
            if hunks:
                print()
            print("skipped")
            _print_findings(remaining)
        if apply:
            return 0 if not any(f.status != EXTERNAL for f in remaining) else 1
        return 0 if not problems else 1
    finally:
        store.close()


def _cmd_impact(root: Path, config: Config, raw_target: str, *, as_json: bool) -> int:
    store = _open_store(root)
    try:
        _require_fresh(root, store, config)
        files = store.listed_paths()
        target = resolve_target(raw_target, root, files, cwd=Path.cwd())
        if target.path is None:
            if target.candidates:
                print("ambiguous path; candidates:", file=sys.stderr)
                for path in target.candidates:
                    print(path, file=sys.stderr)
                return 1
            raise CliError(target.error or "not in index")
        result = impact_for(store, target.path)
        if as_json:
            print(json.dumps(impact_json(result), indent=2))
            return 0
        _print_impact(result)
        return 0
    finally:
        store.close()


def _open_store(root: Path, *, code: int = 1) -> GraphStore:
    path = db_path(root)
    if not path.is_file():
        raise CliError("index not found; run `textgraph init`", code=code)
    return GraphStore(path)


def _require_fresh(root: Path, store: GraphStore, config: Config, *, code: int = 1) -> None:
    if is_index_stale(root, store, config):
        raise CliError("index is stale; run `textgraph sync`", code=code)


def _print_impact(result: ImpactResult) -> None:
    print(f"target: {result.target}")
    print()
    print("inbound")
    _print_table(
        ("source", "raw", "line", "confidence"),
        [(edge.source, edge.raw, str(edge.line), edge.confidence) for edge in result.inbound],
    )
    print()
    print("outbound")
    _print_table(
        ("raw", "resolved", "line", "confidence"),
        [
            (edge.raw, edge.resolved or "", str(edge.line), edge.confidence)
            for edge in result.outbound
        ],
    )
    if result.unresolved:
        print()
        print("unresolved")
        _print_table(
            ("raw", "line"),
            [(edge.raw, str(edge.line)) for edge in result.unresolved],
        )


def _print_findings(findings: Sequence[Finding]) -> None:
    _print_table(
        ("source", "line", "raw", "status", "suggested", "confidence"),
        [
            (
                finding.source,
                str(finding.line),
                finding.raw,
                finding.status,
                ", ".join(finding.suggested),
                finding.confidence,
            )
            for finding in findings
        ],
    )


def _print_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    if not rows:
        print("(none)")
        return
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    for row in rows:
        print("  ".join(row[index].ljust(widths[index]) for index in range(len(headers))))
