from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from vscode_profiles.apply import run_apply, run_remove
from vscode_profiles.diff import groups_json, status_for, values_json
from vscode_profiles.errors import CliError
from vscode_profiles.keys import check_selectors, select_keys
from vscode_profiles.paths import resolve_user_data_dir
from vscode_profiles.profiles import load_profiles, read_own_settings

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def tool_version() -> str:
    data = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


def maybe_print_version(argv: Sequence[str] | None) -> bool:
    raw = list(argv if argv is not None else sys.argv[1:])
    if raw == ["--version"]:
        print(f"vscode-profiles {tool_version()}")
        return True
    return False


def main(argv: Sequence[str] | None = None) -> int:
    if maybe_print_version(argv):
        return 0
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command is None:
        parser.print_usage(sys.stderr)
        return 2
    try:
        if args.command == "list":
            return _cmd_list(args.user_data_dir)
        if args.command == "diff":
            return _cmd_diff(
                args.user_data_dir,
                keys=args.key,
                prefix=args.prefix,
                exclude=args.exclude_key,
                mask=args.mask,
                by_profile=args.by_profile,
            )
        if args.command == "apply":
            return run_apply(
                args.user_data_dir,
                source=args.source,
                destinations=args.to,
                keys=args.key,
                prefix=args.prefix,
                exclude=args.exclude_key,
                mask=args.mask,
                write=args.write,
                force=args.force,
            )
        if args.command == "remove":
            return run_remove(
                args.user_data_dir,
                targets=args.profile,
                keys=args.key,
                prefix=args.prefix,
                exclude=args.exclude_key,
                mask=args.mask,
                write=args.write,
                force=args.force,
            )
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    parser.print_usage(sys.stderr)
    return 2


def _cmd_list(user_data_dir: Path | None) -> int:
    profiles = load_profiles(resolve_user_data_dir(user_data_dir))
    for profile in profiles:
        if profile.inherits_settings:
            kind = "inherit"
            count = 0
        else:
            kind = "own"
            count = len(read_own_settings(profile))
        print(f"{profile.name}\t{kind}\t{count}")
    return 0


def _cmd_diff(
    user_data_dir: Path | None,
    keys: list[str],
    prefix: str | None,
    exclude: list[str],
    mask: bool,
    by_profile: bool = False,
) -> int:
    check_selectors(keys, prefix, exclude)
    profiles = load_profiles(resolve_user_data_dir(user_data_dir))
    loaded = [
        (profile.name, read_own_settings(profile))
        for profile in profiles
        if not profile.inherits_settings
    ]
    selected = select_keys({name for _, values in loaded for name in values}, keys, prefix, exclude)
    show_values = bool(keys) or prefix is not None
    for key in selected:
        status = status_for(loaded, key)
        if by_profile:
            print(f"{key}\t{status}\t{groups_json(loaded, key)}")
        elif show_values:
            print(f"{key}\t{status}\t{values_json(loaded, key, mask=mask)}")
        else:
            print(f"{key}\t{status}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vscode-profiles",
        description="List, diff, and apply VS Code stable user profile settings keys",
    )
    parser.add_argument(
        "--user-data-dir",
        type=Path,
        default=None,
        help="VS Code stable user data directory (default: the platform Code directory)",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list", help="show profile name, inheritance, and own key count")
    diff = sub.add_parser("diff", help="compare own top-level settings keys")
    diff.add_argument(
        "--key",
        action="append",
        default=[],
        help="top-level key to compare; also prints values",
    )
    diff.add_argument(
        "--prefix",
        default=None,
        help="top-level keys that start with this prefix; also prints values",
    )
    _add_exclude(diff)
    _add_mask(diff)
    diff.add_argument(
        "--by-profile",
        action="store_true",
        help="print which profiles have each key as value-group numbers, never the values",
    )
    apply = sub.add_parser("apply", help="overwrite selected keys from a source profile")
    apply.add_argument("--from", dest="source", required=True, help="profile that supplies values")
    apply.add_argument(
        "--to",
        dest="to",
        action="append",
        required=True,
        help="destination profile name; repeat, or pass all for every other own profile",
    )
    apply.add_argument(
        "--key", action="append", default=[], help="top-level key to copy; repeatable"
    )
    apply.add_argument(
        "--prefix",
        default=None,
        help="top-level source keys that start with this prefix",
    )
    _add_exclude(apply)
    _add_mask(apply)
    _add_write(apply)
    remove = sub.add_parser("remove", help="delete selected top-level keys from profiles")
    remove.add_argument(
        "--profile",
        action="append",
        required=True,
        help="profile to edit; repeat, or pass all for every own profile",
    )
    remove.add_argument(
        "--key", action="append", default=[], help="top-level key to delete; repeatable"
    )
    remove.add_argument(
        "--prefix",
        default=None,
        help="top-level keys that start with this prefix",
    )
    _add_exclude(remove)
    _add_mask(remove)
    _add_write(remove)
    return parser


def _add_write(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--write", action="store_true", help="write the settings.json files")
    parser.add_argument(
        "--force",
        action="store_true",
        help="write even if VS Code stable (Code) is running",
    )


def _add_exclude(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--exclude-key",
        action="append",
        default=[],
        help="top-level key to leave out of the selection; repeatable",
    )


def _add_mask(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mask",
        action="store_true",
        help="print strings inside values as *** (object keys and other types stay)",
    )
