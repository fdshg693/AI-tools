from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from vscode_profiles.apply import run_apply
from vscode_profiles.diff import status_for, values_json
from vscode_profiles.errors import CliError
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
            return _cmd_diff(args.user_data_dir, keys=args.key, prefix=args.prefix)
        if args.command == "apply":
            return run_apply(
                args.user_data_dir,
                source=args.source,
                destinations=args.to,
                keys=args.key,
                prefix=args.prefix,
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


def _cmd_diff(user_data_dir: Path | None, keys: list[str], prefix: str | None) -> int:
    if prefix == "":
        raise CliError("prefix must not be empty", code=2)
    if any(key == "" for key in keys):
        raise CliError("key must not be empty", code=2)
    profiles = load_profiles(resolve_user_data_dir(user_data_dir))
    loaded = [
        (profile.name, read_own_settings(profile))
        for profile in profiles
        if not profile.inherits_settings
    ]
    selected = _selected_keys(loaded, keys, prefix)
    show_values = bool(keys) or prefix is not None
    for key in selected:
        status = status_for(loaded, key)
        if show_values:
            print(f"{key}\t{status}\t{values_json(loaded, key)}")
        else:
            print(f"{key}\t{status}")
    return 0


def _selected_keys(
    loaded: list[tuple[str, dict[str, object]]],
    keys: list[str],
    prefix: str | None,
) -> list[str]:
    wanted = set(keys)
    found: list[str] = []
    for key in sorted({name for _, values in loaded for name in values}):
        if wanted and key not in wanted:
            continue
        if prefix is not None and not key.startswith(prefix):
            continue
        found.append(key)
    return found


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
    apply.add_argument("--write", action="store_true", help="write destination settings.json files")
    apply.add_argument(
        "--force",
        action="store_true",
        help="write even if VS Code stable (Code) is running",
    )
    return parser
