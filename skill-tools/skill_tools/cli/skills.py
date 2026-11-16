"""Skill list-skills, install-skills, installed-skills, update-skills, remove-skills commands."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from ..catalog import discover_catalog, select_records
from ..config import INSTALL_MODES, create_source
from ..install.installer import (
    InstallPlan,
    _project_install_lock,
    build_plan,
    execute_install,
    execute_remove,
    load_project_manifest,
    recover_transaction,
)
from ..install.manifest import (
    bundle_file_hashes,
    link_store_root,
    verify_entry,
    verify_link_entry,
    verify_managed_entry,
)
from ..install.store import Referrer, Store, entry_relative_path, install_links
from ..models import ConfigError, InstallError, SkillBundle
from ..source import display_skill_path
from ..install.scope import (
    InstallScope,
    ensure_not_store_state,
    ensure_outside_store,
    ensure_project_root_allowed,
)
from .arguments import (
    _add_runtime_arguments,
    _add_scope_arguments,
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
    _add_scope_arguments(parser, global_option=True)
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
    parser.add_argument(
        "--mode",
        choices=INSTALL_MODES,
        default=None,
        help=(
            "copy the skill into the project, or link it to one shared copy in the skill "
            "store (default: install_mode from the config, else copy)"
        ),
    )


def _add_managed_commands(commands) -> None:
    installed = commands.add_parser(
        "installed-skills", help="list skills recorded in this project's managed manifest"
    )
    _add_scope_arguments(installed, global_option=True)
    installed.add_argument("--json", action="store_true", help="write managed entries as JSON")

    update = commands.add_parser("update-skills", help="update skills managed in this project")
    _add_runtime_arguments(update)
    _add_scope_arguments(update, global_option=True)
    update.add_argument("skills", nargs="*", help="canonical skill IDs or unique bundle names")
    update.add_argument(
        "--dry-run", action="store_true", help="show update targets without copying"
    )
    update.add_argument("--force", action="store_true", help="replace drifted managed directories")

    remove = commands.add_parser(
        "remove-skills", help="remove skills recorded in this project's manifest"
    )
    _add_scope_arguments(remove, global_option=True)
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


def _command_install(args: argparse.Namespace, cwd: Path, scope: InstallScope) -> int:
    ensure_project_root_allowed(scope, "install-skills")
    root, state_dir = scope.root, scope.state_dir
    with _project_install_lock(root, state_dir=state_dir):
        recover_transaction(root, state_dir=state_dir)
    config = _load_runtime_config(args, cwd, scope=scope)
    mode = _resolve_install_mode(args.mode, config.install_mode, scope)
    ensure_outside_store(scope, config.store.path)
    source = create_source(config)
    selectors = [config.self_skill if token == SELF_SELECTOR else token for token in args.skills]
    selected = tuple(
        record.bundle
        for record in select_records(
            discover_catalog(source), selectors, source_descriptor=source.descriptor
        )
    )
    targets = tuple(args.target.split(",")) if args.target is not None else None
    plan = build_plan(
        root,
        selected,
        config,
        args.overwrite,
        targets=targets,
        state_dir=state_dir,
        global_scope=scope.is_global,
    )
    store = Store.from_config(config)
    for item in plan:
        action = "would install" if args.dry_run else "install"
        path = display_skill_path(item.bundle.canonical_id, source.descriptor)
        # Copies keep the historical columns; a link adds the store copy it points at.
        suffix = ""
        if mode == "link":
            store_path = entry_relative_path(source.descriptor, item.bundle)
            suffix = f"\t(link -> {store.root.joinpath(*store_path.split('/'))})"
        if item.target_name is None:
            shown = scope.display(item.target) if scope.is_global else item.target
            print(f"{action}\t{path}\t{shown}{suffix}")
        else:
            relative_target = scope.display(item.target)
            print(
                f"{action}\t{path}\t{item.bundle.canonical_id}"
                f"\t{item.target_name}\t{relative_target}{suffix}"
            )
    if mode == "link":
        for item in plan:
            store.ensure_outside(item.target.parent, "skill destination")
    if args.dry_run:
        return 0
    previous = {entry["installPath"].casefold(): entry for entry in _managed_entries(scope)}
    if mode == "link":
        install_links(store, source, plan, root, overwrite=args.overwrite, state_dir=state_dir)
        return 0
    execute_install(source, plan, root, overwrite=args.overwrite, state_dir=state_dir)
    # Copies replaced links: their store entries lose these referrers.
    unlinked = [
        entry["installPath"]
        for item in plan
        if (entry := previous.get(item.target.relative_to(root).as_posix().casefold()))
        and entry["mode"] == "link"
    ]
    if unlinked:
        _forget_referrers(store, root, unlinked)
    return 0


def _resolve_install_mode(requested: str | None, configured: str, scope: InstallScope) -> str:
    """`--mode` wins over `install_mode`; --global always copies.

    An explicit `--mode link --global` is refused. A configured `install_mode:
    link` falls back to copy there with a note, so a global config that prefers
    links still allows `install-skills --global`.
    """

    if scope.is_global and (requested or configured) == "link":
        if requested == "link":
            raise ConfigError(
                "--mode link cannot be used with --global (the user-wide location is a single "
                "place, so linking it to the store gains nothing)"
            )
        print("note: install_mode link does not apply to --global; copying", file=sys.stderr)
        return "copy"
    return requested or configured


def _forget_referrers(store: Store, root: Path, install_paths: Sequence[str]) -> None:
    """Best effort: a record left behind is dropped by `store gc` once no link exists."""

    try:
        store.remove_referrers(root, install_paths)
    except (InstallError, OSError) as exc:
        print(
            f"warning: could not update the skill store's referrer records: {exc}",
            file=sys.stderr,
        )


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


def _managed_entries(scope: InstallScope) -> list[dict]:
    with _project_install_lock(scope.root, state_dir=scope.state_dir):
        recover_transaction(scope.root, state_dir=scope.state_dir)
        return load_project_manifest(scope.root, state_dir=scope.state_dir)["entries"]


def _command_installed(args: argparse.Namespace, cwd: Path, scope: InstallScope) -> int:
    entries = _managed_entries(scope)
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
    elif not entries:
        print("(no managed skills)")
    else:
        print("canonical_id\ttarget\tinstall_path\tsource\tmode")
        for entry in entries:
            source = entry["source"]
            source_label = (
                f"local {source.get('path')}"
                if source.get("type") == "local"
                else f"github {source.get('owner')}/{source.get('repository')}@{source.get('ref')}"
            )
            print(
                f"{entry['canonicalId']}\t{entry['target'] or '(default)'}\t"
                f"{entry['installPath']}\t{source_label}\t{entry['mode']}"
            )
    return 0


def _command_remove(args: argparse.Namespace, cwd: Path, scope: InstallScope) -> int:
    root = scope.root
    ensure_not_store_state(scope)
    entries = _managed_entries(scope)
    selected = _select_managed_entries(entries, args.skills)
    if not selected:
        print("(no managed skills)")
        return 0
    stores: dict[Path, list[str]] = {}
    for entry in selected:
        path = verify_managed_entry(root, entry, force=args.force)
        action = "would remove" if args.dry_run else "remove"
        if entry["mode"] == "link":
            suffix = " (link only; the shared store entry is kept)"
            store_root = link_store_root(path, entry)
            if store_root is not None:
                stores.setdefault(store_root, []).append(entry["installPath"])
        else:
            suffix = " (force: directory contents may be deleted)" if args.force else ""
        print(f"{action}\t{entry['canonicalId']}\t{scope.display(path)}{suffix}")
    if not args.dry_run:
        execute_remove(root, selected, force=args.force, state_dir=scope.state_dir)
        for store_root, paths in stores.items():
            _forget_referrers(Store(store_root), root, paths)
    return 0


def _command_update(args: argparse.Namespace, cwd: Path, scope: InstallScope) -> int:
    ensure_project_root_allowed(scope, "update-skills")
    root = scope.root
    selected = _select_managed_entries(_managed_entries(scope), args.skills)
    if not selected:
        print("(no managed skills)")
        return 0
    config = _load_runtime_config(args, cwd, scope=scope)
    ensure_outside_store(scope, config.store.path)
    source = create_source(config)
    matching = tuple(entry for entry in selected if _entry_matches_source(entry, source, root))
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
    copied: list[dict] = []
    store = Store.from_config(config)
    link_bundles: dict[str, SkillBundle] = {}
    link_referrers: list[Referrer] = []
    shown_links: list[tuple[dict, Path]] = []
    store_entries = (
        {item.store_path.casefold(): item for item in store.list_entries()}
        if any(entry["mode"] == "link" for entry in matching)
        else {}
    )
    action = "would update" if args.dry_run else "update"
    for entry in matching:
        record = records.get(entry["canonicalId"])
        if record is None:
            print(
                f"warning: {entry['canonicalId']} is no longer in the catalog; keeping installed files",
                file=sys.stderr,
            )
            continue
        if entry["mode"] == "link":
            link = verify_link_entry(root, entry, store_root=store.root, force=args.force)
            expected = entry_relative_path(source.descriptor, record.bundle)
            if expected.casefold() != entry["store"].casefold():
                raise InstallError(
                    f"managed link {entry['installPath']} points at store entry {entry['store']}, "
                    f"but the configured source maps it to {expected}; reinstall it with "
                    "`install-skills --overwrite`"
                )
            store_entry = store_entries.get(entry["store"].casefold())
            if store_entry is not None and _unchanged(
                source, record.bundle, store.root, store_entry.entry
            ):
                print(f"unchanged	{entry['canonicalId']}	{scope.display(link)}")
                continue
            # One refresh per store entry, however many links select it.
            link_bundles.setdefault(entry["store"].casefold(), record.bundle)
            link_referrers.append(
                Referrer(root, entry["installPath"], entry["canonicalId"], entry["store"])
            )
            shown_links.append((entry, link))
            continue
        target = verify_entry(root, entry, force=args.force)
        if _unchanged(source, record.bundle, root, entry):
            print(f"unchanged	{entry['canonicalId']}	{scope.display(target)}")
            continue
        plan = InstallPlan(
            bundle=record.bundle,
            target=target,
            target_name=entry["target"],
            overwrite=True,
        )
        plans.append(plan)
        copied.append(entry)
        suffix = " (force: directory contents may be replaced)" if args.force else ""
        print(f"{action}	{entry['canonicalId']}	{scope.display(target)}{suffix}")
    for entry, link in shown_links:
        store_entry = store_entries.get(entry["store"].casefold())
        shared = len(store_entry.referrers) if store_entry is not None else 0
        suffix = " (force: store entry contents may be replaced)" if args.force else ""
        print(
            f"{action}	{entry['canonicalId']}	{scope.display(link)}"
            f"	(shared: store entry {entry['store']} has {shared} link(s)){suffix}"
        )
    if plans and not args.dry_run:
        execute_install(
            source,
            tuple(plans),
            root,
            overwrite=True,
            managed_entries=tuple(copied),
            force_managed=args.force,
            state_dir=scope.state_dir,
        )
    if link_bundles and not args.dry_run:
        # Refreshing the store entry updates every project that links to it; the
        # project links stay as they are. The referrers are re-recorded so a store
        # entry re-created under --force is not garbage collected.
        store.ensure(
            source,
            tuple(link_bundles.values()),
            referrers=link_referrers,
            refresh=True,
            force=args.force,
        )
    return 0


def _unchanged(source, bundle: SkillBundle, root: Path, entry: dict) -> bool:
    """True when the source bundle equals the recorded copy and the copy has not drifted.

    ``bundle.files`` is the policy-filtered set, so it is compared with the
    manifest record rather than the raw source directory. A drifted copy (only
    reachable here under --force) is never unchanged: --force must restore it.
    """

    if bundle_file_hashes(source, bundle) != entry["files"]:
        return False
    try:
        verify_entry(root, entry)
    except InstallError:
        return False
    return True
