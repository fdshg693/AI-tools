"""Skill list-skills, install-skills, installed-skills, update-skills, remove-skills commands."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from ..catalog import discover_catalog, select_records
from ..config import create_source
from ..install.installer import (
    InstallPlan,
    _project_install_lock,
    build_plan,
    execute_install,
    execute_remove,
    load_project_manifest,
    recover_transaction,
)
from ..install.manifest import verify_entry
from ..models import InstallError
from ..source import display_skill_path
from .arguments import (
    _add_runtime_arguments,
    _entry_matches_source,
    _load_runtime_config,
    _source_description,
)

SELF_SELECTOR = "self"


def _add_list_command(commands) -> None:
    parser = commands.add_parser(
        "list-skills", help="list deployable skills as source path, name, and file count"
    )
    _add_runtime_arguments(parser)


def _add_install_command(commands) -> None:
    parser = commands.add_parser(
        "install-skills", help="install skills selected by source path, unique name, or `self`"
    )
    _add_runtime_arguments(parser)
    parser.add_argument(
        "skills",
        nargs="+",
        help=(
            "absolute path, GitHub blob URL, canonical ID, unique name, "
            "or `self` (the configured skill-tools companion skill)"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show destinations without copying files"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing destination skill directory",
    )
    parser.add_argument(
        "--target",
        help="install to configured target name(s), comma-separated",
    )


def _add_managed_commands(commands) -> None:
    installed = commands.add_parser(
        "installed-skills", help="list skills recorded in this project's managed manifest"
    )
    installed.add_argument("--json", action="store_true", help="write managed entries as JSON")

    update = commands.add_parser("update-skills", help="update skills managed in this project")
    _add_runtime_arguments(update)
    update.add_argument("skills", nargs="*", help="canonical skill IDs or unique bundle names")
    update.add_argument(
        "--dry-run", action="store_true", help="show update targets without copying"
    )
    update.add_argument("--force", action="store_true", help="replace drifted managed directories")

    remove = commands.add_parser(
        "remove-skills", help="remove skills recorded in this project's manifest"
    )
    remove.add_argument("skills", nargs="*", help="canonical skill IDs or bundle names")
    remove.add_argument("--dry-run", action="store_true", help="show directories without removing")
    remove.add_argument(
        "--force",
        action="store_true",
        help="delete drifted managed directories, including unrecorded files",
    )


def _command_list(args: argparse.Namespace, cwd: Path) -> int:
    config = _load_runtime_config(args, cwd)
    source = create_source(config)
    records = discover_catalog(source)
    for record in records:
        path = display_skill_path(record.canonical_id, source.descriptor)
        print(f"{path}\t{record.bundle.name}\t{len(record.files)}")
    print(f"source: {_source_description(source)}", file=sys.stderr)
    return 0


def _command_install(args: argparse.Namespace, cwd: Path) -> int:
    with _project_install_lock(cwd):
        recover_transaction(cwd)
    config = _load_runtime_config(args, cwd)
    source = create_source(config)
    selectors = [config.self_skill if token == SELF_SELECTOR else token for token in args.skills]
    selected = tuple(
        record.bundle
        for record in select_records(
            discover_catalog(source), selectors, source_descriptor=source.descriptor
        )
    )
    targets = tuple(args.target.split(",")) if args.target is not None else None
    plan = build_plan(cwd, selected, config, args.overwrite, targets=targets)
    for item in plan:
        action = "would install" if args.dry_run else "install"
        path = display_skill_path(item.bundle.canonical_id, source.descriptor)
        if item.target_name is None:
            print(f"{action}\t{path}\t{item.target}")
        else:
            relative_target = item.target.relative_to(cwd).as_posix()
            print(
                f"{action}\t{path}\t{item.bundle.canonical_id}"
                f"\t{item.target_name}\t{relative_target}"
            )
    if args.dry_run:
        return 0
    execute_install(source, plan, cwd, overwrite=args.overwrite)
    return 0


def _select_managed_entries(entries: Sequence[dict], selectors: Sequence[str]) -> tuple[dict, ...]:
    if not selectors:
        return tuple(entries)
    selected: list[dict] = []
    for selector in selectors:
        matches = [entry for entry in entries if entry["canonicalId"] == selector]
        if not matches:
            matches = [entry for entry in entries if entry["installPath"] == selector]
        if not matches:
            matches = [entry for entry in entries if entry["bundleName"] == selector]
        if not matches:
            raise InstallError(f"no managed installation matches {selector!r}")
        if len({entry["canonicalId"] for entry in matches}) > 1:
            raise InstallError(f"managed installation selector is ambiguous: {selector!r}")
        selected.extend(entry for entry in matches if entry not in selected)
    return tuple(selected)


def _command_installed(args: argparse.Namespace, cwd: Path) -> int:
    with _project_install_lock(cwd):
        recover_transaction(cwd)
        entries = load_project_manifest(cwd)["entries"]
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
    elif not entries:
        print("(no managed skills)")
    else:
        print("canonical_id\ttarget\tinstall_path\tsource")
        for entry in entries:
            source = entry["source"]
            source_label = (
                f"local {source.get('path')}"
                if source.get("type") == "local"
                else f"github {source.get('owner')}/{source.get('repository')}@{source.get('ref')}"
            )
            print(
                f"{entry['canonicalId']}\t{entry['target'] or '(default)'}\t"
                f"{entry['installPath']}\t{source_label}"
            )
    return 0


def _command_remove(args: argparse.Namespace, cwd: Path) -> int:
    with _project_install_lock(cwd):
        recover_transaction(cwd)
        entries = load_project_manifest(cwd)["entries"]
    selected = _select_managed_entries(entries, args.skills)
    if not selected:
        print("(no managed skills)")
        return 0
    for entry in selected:
        path = verify_entry(cwd, entry, force=args.force)
        action = "would remove" if args.dry_run else "remove"
        suffix = " (force: directory contents may be deleted)" if args.force else ""
        print(f"{action}\t{entry['canonicalId']}\t{path.relative_to(cwd).as_posix()}{suffix}")
    if not args.dry_run:
        execute_remove(cwd, selected, force=args.force)
    return 0


def _command_update(args: argparse.Namespace, cwd: Path) -> int:
    with _project_install_lock(cwd):
        recover_transaction(cwd)
        entries = load_project_manifest(cwd)["entries"]
        selected = _select_managed_entries(entries, args.skills)
    if not selected:
        print("(no managed skills)")
        return 0
    config = _load_runtime_config(args, cwd)
    source = create_source(config)
    matching = tuple(entry for entry in selected if _entry_matches_source(entry, source, cwd))
    for entry in selected:
        if entry not in matching:
            if args.skills:
                raise InstallError(
                    f"configured source does not match managed entry {entry['canonicalId']}; "
                    "refusing an implicit source switch"
                )
            print(
                f"warning: source changed for {entry['canonicalId']}; not updating it",
                file=sys.stderr,
            )
    if not matching:
        return 0

    records = {record.canonical_id: record for record in discover_catalog(source)}
    plans: list[InstallPlan] = []
    for entry in matching:
        record = records.get(entry["canonicalId"])
        if record is None:
            print(
                f"warning: {entry['canonicalId']} is no longer in the catalog; keeping installed files",
                file=sys.stderr,
            )
            continue
        target = verify_entry(cwd, entry, force=args.force)
        plan = InstallPlan(
            bundle=record.bundle,
            target=target,
            target_name=entry["target"],
            overwrite=True,
        )
        plans.append(plan)
        action = "would update" if args.dry_run else "update"
        suffix = " (force: directory contents may be replaced)" if args.force else ""
        print(f"{action}\t{entry['canonicalId']}\t{target.relative_to(cwd).as_posix()}{suffix}")
    if plans and not args.dry_run:
        execute_install(
            source,
            tuple(plans),
            cwd,
            overwrite=True,
            managed_entries=tuple(
                entry
                for entry in matching
                if entry["canonicalId"] in {p.bundle.canonical_id for p in plans}
            ),
            force_managed=args.force,
        )
    return 0
