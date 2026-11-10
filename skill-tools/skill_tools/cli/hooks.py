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
    parse_agents,
    select_install_targets,
    select_managed_hooks,
)
from ..install.installer import (
    _project_install_lock,
    load_project_manifest,
    recover_transaction,
)
from ..models import InstallError
from .arguments import (
    _add_runtime_arguments,
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
        "install", help="copy hooks into this project and register them for the chosen agents"
    )
    _add_runtime_arguments(install)
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
    installed.add_argument("--json", action="store_true", help="write managed hooks as JSON")

    update = subcommands.add_parser("update", help="update hooks managed in this project")
    _add_runtime_arguments(update)
    update.add_argument("hooks", nargs="*", help="managed hook ids (default: every managed hook)")
    update.add_argument("--agent", help=f"only update these agents ({agent_help})")
    update.add_argument("--dry-run", action="store_true", help="show changes without applying")
    update.add_argument(
        "--force",
        action="store_true",
        help="replace modified hook files and skip registrations edited by hand",
    )

    remove = subcommands.add_parser("remove", help="remove hooks managed in this project")
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


def _print_hook_changes(result: HookChangeSet, dry_run: bool) -> None:
    for warning in dict.fromkeys(result.warnings):
        print(f"warning: {warning}", file=sys.stderr)
    if not result.actions:
        print("(no changes)")
    for verb, *fields in result.actions:
        passive = verb in {"unchanged", "keep-seed"}
        print("\t".join([f"would {verb}" if dry_run and not passive else verb, *fields]))


def _command_hooks_install(args: argparse.Namespace, cwd: Path) -> int:
    with _project_install_lock(cwd):
        recover_transaction(cwd)
    config = _load_runtime_config(args, cwd)
    agents = parse_agents(args.agent, config.hooks)
    source = create_source(config)
    targets, warnings_ = select_install_targets(
        load_hook_catalog(source), args.hooks, agents, config.hooks, source, cwd
    )
    result = apply_hook_changes(
        cwd,
        source=source,
        hooks_config=config.hooks,
        install=targets,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )
    result.warnings[:0] = warnings_
    _print_hook_changes(result, args.dry_run)
    print(f"source: {_source_description(source)}", file=sys.stderr)
    return 0


def _managed_hooks(cwd: Path) -> list[dict]:
    with _project_install_lock(cwd):
        recover_transaction(cwd)
        return load_project_manifest(cwd)["hooks"]


def _selected_managed_hooks(args: argparse.Namespace, cwd: Path) -> tuple[dict, ...]:
    agents = None if args.agent is None else parse_agents(args.agent, HooksConfig())
    return select_managed_hooks(_managed_hooks(cwd), args.hooks, agents)


def _command_hooks_installed(args: argparse.Namespace, cwd: Path) -> int:
    entries = _managed_hooks(cwd)
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
    elif not entries:
        print("(no managed hooks)")
    else:
        print("hook_id\tagent\tinstall_dir\tregistered_in\tsource")
        for entry in entries:
            source = entry["source"]
            source_label = (
                f"local {source.get('path')}"
                if source.get("type") == "local"
                else f"github {source.get('owner')}/{source.get('repository')}@{source.get('ref')}"
            )
            files = sorted({item["file"] for item in entry["registrations"]}) or [
                "(placement only)"
            ]
            print(
                f"{entry['hookId']}\t{entry['agent']}\t{entry['installDir']}\t"
                f"{','.join(files)}\t{source_label}"
            )
    return 0


def _command_hooks_update(args: argparse.Namespace, cwd: Path) -> int:
    selected = _selected_managed_hooks(args, cwd)
    if not selected:
        print("(no managed hooks)")
        return 0
    config = _load_runtime_config(args, cwd)
    source = create_source(config)
    warnings_: list[str] = []
    matching: list[dict] = []
    for entry in selected:
        if _entry_matches_source(entry, source, cwd):
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
        ensure_installable(hook, source, cwd)
        removals.append(entry)
        targets.append(HookTarget(hook, spec, entry["installDir"]))
    result = HookChangeSet()
    if targets:
        result = apply_hook_changes(
            cwd,
            source=source,
            hooks_config=config.hooks,
            remove=removals,
            install=targets,
            force=args.force,
            dry_run=args.dry_run,
        )
    result.warnings[:0] = warnings_
    _print_hook_changes(result, args.dry_run)
    return 0


def _command_hooks_remove(args: argparse.Namespace, cwd: Path) -> int:
    selected = _selected_managed_hooks(args, cwd)
    if not selected:
        print("(no managed hooks)")
        return 0
    # Removal needs no source or config: every path it touches is in the manifest.
    result = apply_hook_changes(cwd, remove=selected, force=args.force, dry_run=args.dry_run)
    _print_hook_changes(result, args.dry_run)
    return 0
