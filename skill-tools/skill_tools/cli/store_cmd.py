"""`store list|update|gc`: the shared skill store that link installs point at.

The store belongs to no project, so these commands take no `--project-dir` or
`--global`; they read `store.path` from the config (global config, then the
current directory's skill-tools.yaml, or `--config`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..catalog import discover_catalog
from ..config import create_source
from ..install.store import Store, entry_relative_path
from ..models import InstallError
from ..source import display_skill_path
from .arguments import _add_runtime_arguments, _entry_matches_source, _load_runtime_config
from .skills import _select_managed_entries


def _add_store_command(commands) -> None:
    store = commands.add_parser(
        "store", help="inspect and maintain the shared skill store used by --mode link"
    )
    subcommands = store.add_subparsers(dest="store_command", required=True)

    list_command = subcommands.add_parser(
        "list", help="list store entries with the number of recorded links"
    )
    _add_runtime_arguments(list_command, index_path=False)
    list_command.add_argument("--json", action="store_true", help="write store entries as JSON")

    update = subcommands.add_parser(
        "update",
        help="refresh store entries from the configured source (every linked project follows)",
    )
    _add_runtime_arguments(update, index_path=False)
    update.add_argument(
        "skills", nargs="*", help="canonical skill IDs, bundle names, or store paths"
    )
    update.add_argument("--dry-run", action="store_true", help="show entries without copying")
    update.add_argument(
        "--force", action="store_true", help="replace store entries whose files were edited"
    )

    gc = subcommands.add_parser("gc", help="remove store entries that no project links to")
    _add_runtime_arguments(gc, index_path=False)
    gc.add_argument("--dry-run", action="store_true", help="show entries without removing")


def _store(args: argparse.Namespace, cwd: Path) -> tuple[Store, object]:
    config = _load_runtime_config(args, cwd)
    print(f"store: {config.store.path}", file=sys.stderr)
    return Store.from_config(config), config


def _source_label(source: dict) -> str:
    if source.get("type") == "local":
        return f"local {source.get('path')}"
    return f"github {source.get('owner')}/{source.get('repository')}@{source.get('ref')}"


def _command_store_list(args: argparse.Namespace, cwd: Path) -> int:
    store, _ = _store(args, cwd)
    entries = store.list_entries()
    if args.json:
        payload = [
            {
                "storePath": item.store_path,
                "path": str(item.path),
                "canonicalId": item.canonical_id,
                "bundleName": item.entry["bundleName"],
                "source": item.entry["source"],
                "referrers": [
                    {"projectRoot": str(ref.project_root), "installPath": ref.install_path}
                    for ref in item.referrers
                ],
            }
            for item in entries
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif not entries:
        print("(no store entries)")
    else:
        print("store_path\tcanonical_id\tlinks\tsource")
        for item in entries:
            print(
                f"{item.store_path}\t{item.canonical_id}\t{len(item.referrers)}"
                f"\t{_source_label(item.entry['source'])}"
            )
    return 0


def _command_store_update(args: argparse.Namespace, cwd: Path) -> int:
    store, config = _store(args, cwd)
    entries = [item.entry for item in store.list_entries()]
    selected = _select_managed_entries(entries, args.skills)
    if not selected:
        print("(no store entries)")
        return 0
    source = create_source(config)
    matching = [entry for entry in selected if _entry_matches_source(entry, source, store.root)]
    for entry in selected:
        if entry in matching:
            continue
        if args.skills:
            raise InstallError(
                f"configured source does not match store entry {entry['installPath']}; "
                "refusing an implicit source switch"
            )
        print(
            f"warning: {entry['installPath']} comes from another source; not updating it",
            file=sys.stderr,
        )
    if not matching:
        return 0
    records = {record.canonical_id: record for record in discover_catalog(source)}
    counts = {item.store_path.casefold(): len(item.referrers) for item in store.list_entries()}
    bundles = []
    for entry in matching:
        record = records.get(entry["canonicalId"])
        if record is None:
            print(
                f"warning: {entry['canonicalId']} is no longer in the catalog; keeping "
                f"store entry {entry['installPath']}",
                file=sys.stderr,
            )
            continue
        if entry_relative_path(source.descriptor, record.bundle).casefold() != (
            entry["installPath"].casefold()
        ):
            print(
                f"warning: {entry['installPath']} no longer matches the source's bundle; "
                "not updating it",
                file=sys.stderr,
            )
            continue
        bundles.append(record.bundle)
        action = "would update" if args.dry_run else "update"
        shared = counts.get(entry["installPath"].casefold(), 0)
        suffix = " (force: store entry contents may be replaced)" if args.force else ""
        path = display_skill_path(entry["canonicalId"], source.descriptor)
        print(f"{action}\t{entry['installPath']}\t{path}\t({shared} link(s)){suffix}")
    if bundles and not args.dry_run:
        store.ensure(source, tuple(bundles), refresh=True, force=args.force)
    return 0


def _command_store_gc(args: argparse.Namespace, cwd: Path) -> int:
    store, _ = _store(args, cwd)
    result = store.collect_garbage(dry_run=args.dry_run)
    prefix = "would " if args.dry_run else ""
    for referrer in result.pruned_referrers:
        print(f"{prefix}forget\t{referrer.link}\t(no link to {referrer.store_path})")
    for item in result.removed:
        print(f"{prefix}remove\t{item.store_path}\t{item.canonical_id}")
    if not result.removed and not result.pruned_referrers:
        print("(nothing to collect)")
    return 0


STORE_COMMANDS = {
    "list": _command_store_list,
    "update": _command_store_update,
    "gc": _command_store_gc,
}
