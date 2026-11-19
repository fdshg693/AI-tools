"""Agent hook commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import HooksConfig, create_source
from ..hooks.catalog import AGENTS, filter_hooks, hook_payload, load_hook_catalog
from ..hooks.install import (
    HookChangeSet,
    HookTarget,
    apply_hook_changes,
    ensure_installable,
    global_agents,
    parse_agents,
    select_install_targets,
    select_managed_hooks,
)
from ..install.installer import (
    _project_install_lock,
    load_project_manifest,
    recover_transaction,
)
from ..models import ConfigError, InstallError
from ..install.scope import InstallScope, ensure_outside_store, ensure_project_root_allowed
from .arguments import (
    _manifest_source_label,
    _add_runtime_arguments,
    _add_scope_arguments,
    _entry_matches_source,
    _load_runtime_config,
    _source_description,
)


def _add_hooks_command(commands) -> None:
    hooks = commands.add_parser(
        "hooks", help="browse agent hooks published by the source's repo-hooks.yaml"
    )
    subcommands = hooks.add_subparsers(dest="hooks_command", required=True)
    list_command = subcommands.add_parser(
        "list", help="list hooks as hook id, supported agents, and summary"
    )
    _add_runtime_arguments(list_command)
    list_command.add_argument(
        "--agent", choices=AGENTS, help="only show hooks available for this agent"
    )
    list_command.add_argument(
        "--all",
        action="store_true",
        help="also show hooks marked distributable: false (repository-only)",
    )
    list_command.add_argument("--json", action="store_true", help="write hooks as JSON")

    agent_help = "agent name(s), comma-separated: " + ", ".join(AGENTS)
    install = subcommands.add_parser(
        "install",
        help="copy hooks into this project (or with --global the user-wide location) "
        "and register them for the chosen agents",
    )
    _add_runtime_arguments(install)
    _add_scope_arguments(install, global_option=True)
    install.add_argument("hooks", nargs="+", help="hook ids from `skill-tools hooks list`")
    install.add_argument(
        "--agent", help=f"{agent_help} (default: hooks.default_agents from the config)"
    )
    install.add_argument(
        "--dry-run", action="store_true", help="show files and registrations without changes"
    )
    install.add_argument(
        "--overwrite",
        action="store_true",
        help="replace unmanaged files that already exist at the hook's install path",
    )

    installed = subcommands.add_parser(
        "installed", help="list hooks recorded in this project's managed manifest"
    )
    _add_scope_arguments(installed, global_option=True)
    installed.add_argument("--json", action="store_true", help="write managed hooks as JSON")

    update = subcommands.add_parser(
        "update", help="update hooks managed in this project (or with --global, user-wide)"
    )
    _add_runtime_arguments(update)
    _add_scope_arguments(update, global_option=True)
    update.add_argument("hooks", nargs="*", help="managed hook ids (default: every managed hook)")
    update.add_argument("--agent", help=f"only update these agents ({agent_help})")
    update.add_argument("--dry-run", action="store_true", help="show changes without applying")
    update.add_argument(
        "--force",
        action="store_true",
        help="replace modified hook files and skip registrations edited by hand",
    )

    sync = subcommands.add_parser(
        "sync",
        help="make the managed hooks match hooks.install in the config: install the listed "
        "hooks that are missing and remove managed hooks that are no longer listed",
    )
    _add_runtime_arguments(sync)
    _add_scope_arguments(sync, global_option=True)
    sync.add_argument("--dry-run", action="store_true", help="show changes without applying")
    sync.add_argument(
        "--overwrite",
        action="store_true",
        help="replace unmanaged files that already exist at a new hook's install path",
    )
    sync.add_argument(
        "--force",
        action="store_true",
        help="delete modified hook files of unlisted hooks and skip registrations edited by hand",
    )

    remove = subcommands.add_parser(
        "remove", help="remove hooks managed in this project (or with --global, user-wide)"
    )
    _add_scope_arguments(remove, global_option=True)
    remove.add_argument("hooks", nargs="*", help="managed hook ids (default: every managed hook)")
    remove.add_argument("--agent", help=f"only remove these agents ({agent_help})")
    remove.add_argument("--dry-run", action="store_true", help="show changes without applying")
    remove.add_argument(
        "--force",
        action="store_true",
        help="delete modified hook files and skip registrations edited by hand",
    )


def _command_hooks_list(args: argparse.Namespace, cwd: Path) -> int:
    config = _load_runtime_config(args, cwd)
    source = create_source(config)
    hooks = filter_hooks(load_hook_catalog(source), agent=args.agent, include_private=args.all)
    agents = None if args.agent is None else (args.agent,)
    if args.json:
        print(
            json.dumps([hook_payload(hook, agents) for hook in hooks], ensure_ascii=False, indent=2)
        )
    elif not hooks:
        print("(no hooks)")
    else:
        for hook in hooks:
            summary = hook.description
            if not hook.distributable:
                summary += " (not distributable)"
            print(f"{hook.id}	{','.join(item.agent for item in hook.agents)}	{summary}")
    print(f"source: {_source_description(source)}", file=sys.stderr)
    return 0


def _print_hook_changes(result: HookChangeSet, dry_run: bool, scope: InstallScope) -> None:
    for warning in dict.fromkeys(result.warnings):
        print(f"warning: {warning}", file=sys.stderr)
    if not result.actions:
        print("(no changes)")
    for verb, *fields in result.actions:
        passive = verb in {"unchanged", "keep-seed"}
        if scope.is_global and fields:
            # The last field is a root-relative path (or "<file> <event> [matcher]").
            fields[-1] = f"~/{fields[-1]}"
        print("\t".join([f"would {verb}" if dry_run and not passive else verb, *fields]))


def _command_hooks_install(args: argparse.Namespace, cwd: Path, scope: InstallScope) -> int:
    ensure_project_root_allowed(scope, "hooks install")
    with _project_install_lock(scope.root, state_dir=scope.state_dir):
        recover_transaction(scope.root, state_dir=scope.state_dir)
    config = _load_runtime_config(args, cwd, scope=scope)
    ensure_outside_store(scope, config.store.path)
    agents = parse_agents(args.agent, config.hooks)
    scope_warnings: list[str] = []
    if scope.is_global:
        agents, scope_warnings = global_agents(agents, explicit=args.agent is not None)
    source = create_source(config)
    targets, warnings_ = select_install_targets(
        load_hook_catalog(source),
        args.hooks,
        agents,
        config.hooks,
        source,
        scope.root,
        global_scope=scope.is_global,
    )
    warnings_[:0] = scope_warnings
    result = apply_hook_changes(
        scope.root,
        source=source,
        hooks_config=config.hooks,
        install=targets,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        state_dir=scope.state_dir,
        global_scope=scope.is_global,
    )
    result.warnings[:0] = warnings_
    _print_hook_changes(result, args.dry_run, scope)
    print(f"source: {_source_description(source)}", file=sys.stderr)
    return 0


def _managed_hooks(scope: InstallScope) -> list[dict]:
    with _project_install_lock(scope.root, state_dir=scope.state_dir):
        recover_transaction(scope.root, state_dir=scope.state_dir)
        return load_project_manifest(scope.root, state_dir=scope.state_dir)["hooks"]


def _selected_managed_hooks(args: argparse.Namespace, scope: InstallScope) -> tuple[dict, ...]:
    agents = None if args.agent is None else parse_agents(args.agent, HooksConfig())
    return select_managed_hooks(_managed_hooks(scope), args.hooks, agents)


def _command_hooks_installed(args: argparse.Namespace, cwd: Path, scope: InstallScope) -> int:
    entries = _managed_hooks(scope)
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
    elif not entries:
        print("(no managed hooks)")
    else:
        print("hook_id\tagent\tinstall_dir\tregistered_in\tsource")
        for entry in entries:
            source = entry["source"]
            source_label = _manifest_source_label(source, scope.root)
            files = sorted({item["file"] for item in entry["registrations"]}) or [
                "(placement only)"
            ]
            print(
                f"{entry['hookId']}\t{entry['agent']}\t{entry['installDir']}\t"
                f"{','.join(files)}\t{source_label}"
            )
    return 0


def _command_hooks_update(args: argparse.Namespace, cwd: Path, scope: InstallScope) -> int:
    ensure_project_root_allowed(scope, "hooks update")
    selected = _selected_managed_hooks(args, scope)
    if not selected:
        print("(no managed hooks)")
        return 0
    config = _load_runtime_config(args, cwd, scope=scope)
    ensure_outside_store(scope, config.store.path)
    source = create_source(config)
    warnings_: list[str] = []
    matching: list[dict] = []
    for entry in selected:
        if _entry_matches_source(entry, source, scope.root):
            matching.append(entry)
        elif args.hooks:
            raise InstallError(
                f"configured source does not match managed hook {entry['hookId']} "
                f"({entry['agent']}); refusing an implicit source switch"
            )
        else:
            warnings_.append(
                f"source changed for {entry['hookId']} ({entry['agent']}); not updating it"
            )
    catalog = {hook.id: hook for hook in load_hook_catalog(source)} if matching else {}
    removals: list[dict] = []
    targets: list[HookTarget] = []
    for entry in matching:
        hook = catalog.get(entry["hookId"])
        spec = hook.agent(entry["agent"]) if hook is not None else None
        if hook is None or spec is None:
            warnings_.append(
                f"{entry['hookId']} ({entry['agent']}) is no longer in the catalog; "
                "keeping the installed files"
            )
            continue
        ensure_installable(hook, source, scope.root, global_scope=scope.is_global)
        removals.append(entry)
        targets.append(HookTarget(hook, spec, entry["installDir"]))
    result = HookChangeSet()
    if targets:
        result = apply_hook_changes(
            scope.root,
            source=source,
            hooks_config=config.hooks,
            remove=removals,
            install=targets,
            force=args.force,
            dry_run=args.dry_run,
            state_dir=scope.state_dir,
            global_scope=scope.is_global,
        )
    result.warnings[:0] = warnings_
    _print_hook_changes(result, args.dry_run, scope)
    return 0


def _command_hooks_sync(args: argparse.Namespace, cwd: Path, scope: InstallScope) -> int:
    """Converge the managed hooks on ``hooks.install``; hooks already installed are kept as is."""

    ensure_project_root_allowed(scope, "hooks sync")
    config = _load_runtime_config(args, cwd, scope=scope)
    desired = config.hooks.install
    if not desired:
        where = config.config_path or "skill-tools.yaml"
        raise ConfigError(f"hooks.install is empty in {where}; list the hook ids per agent")
    ensure_outside_store(scope, config.store.path)
    agents = tuple(desired)
    warnings_: list[str] = []
    if scope.is_global:
        agents, warnings_ = global_agents(agents, explicit=False)
    wanted = {(hook_id, agent) for agent in agents for hook_id in desired[agent]}
    managed = _managed_hooks(scope)
    managed_keys = {(entry["hookId"], entry["agent"]) for entry in managed}
    removals = [entry for entry in managed if (entry["hookId"], entry["agent"]) not in wanted]
    source = create_source(config)
    catalog = load_hook_catalog(source)
    targets: list[HookTarget] = []
    for agent in agents:
        missing = [hook_id for hook_id in desired[agent] if (hook_id, agent) not in managed_keys]
        if not missing:
            continue
        selected, selection_warnings = select_install_targets(
            catalog,
            missing,
            (agent,),
            config.hooks,
            source,
            scope.root,
            global_scope=scope.is_global,
        )
        targets.extend(selected)
        warnings_.extend(selection_warnings)
    result = HookChangeSet()
    if removals or targets:
        result = apply_hook_changes(
            scope.root,
            source=source,
            hooks_config=config.hooks,
            remove=removals,
            install=targets,
            overwrite=args.overwrite,
            force=args.force,
            dry_run=args.dry_run,
            state_dir=scope.state_dir,
            global_scope=scope.is_global,
        )
    result.warnings[:0] = warnings_
    _print_hook_changes(result, args.dry_run, scope)
    print(f"source: {_source_description(source)}", file=sys.stderr)
    return 0


def _command_hooks_remove(args: argparse.Namespace, cwd: Path, scope: InstallScope) -> int:
    selected = _selected_managed_hooks(args, scope)
    if not selected:
        print("(no managed hooks)")
        return 0
    # Removal needs no source or config: every path it touches is in the manifest.
    result = apply_hook_changes(
        scope.root,
        remove=selected,
        force=args.force,
        dry_run=args.dry_run,
        state_dir=scope.state_dir,
        global_scope=scope.is_global,
    )
    _print_hook_changes(result, args.dry_run, scope)
    return 0
