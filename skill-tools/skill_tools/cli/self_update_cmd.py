"""`skill-tools self-update`: reinstall the CLI itself from GitHub."""

from __future__ import annotations

import argparse
from pathlib import Path

from .. import self_update
from ..models import InstallError


def _add_self_update_command(commands) -> None:
    parser = commands.add_parser(
        "self-update",
        help=(
            "update this skill-tools CLI to the latest GitHub version (not for editable installs)"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would run without updating"
    )


def _command_self_update(args: argparse.Namespace, cwd: Path) -> int:
    origin = self_update.read_install_origin()
    if origin.kind == "editable":
        where = f" ({origin.editable_path})" if origin.editable_path else ""
        print(
            f"skill-tools is an editable install{where}; it always runs the local clone. "
            "Update it with `git pull` there instead."
        )
        return 0
    if not self_update.uv_tool_environment():
        raise InstallError(
            "skill-tools was not installed with `uv tool install`; "
            "reinstall it that way or update it with the tool you used"
        )
    spec = self_update.requirement_spec(origin)
    command = self_update.update_command(spec)
    if args.dry_run:
        print("would run\t" + " ".join(command))
        return 0
    command = self_update.update_command(spec, self_update.locate_uv())
    print("run\t" + " ".join(command))
    log_path = self_update.run_update(command)
    if log_path is not None:
        print(
            "update started in the background (it replaces the running executable "
            f"after this command exits); progress is written to {log_path}"
        )
    else:
        print("skill-tools updated")
    return 0
