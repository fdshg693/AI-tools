"""Command-line interface for skills, repo tools, workflows, and agent hooks."""

from __future__ import annotations

import argparse
import io
import sys
import tomllib
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ..locations import project_root
from ..models import (
    CatalogError,
    ConfigError,
    EmbeddingError,
    IndexError,
    InstallError,
    SkillToolsError,
    SourceError,
)
from ..runlog import SessionLog, timestamp
from .config_cmd import _add_config_command, _command_config_init, _command_config_show
from .fb_cmd import execute_fb, fb_requested
from .hooks import (
    _add_hooks_command,
    _command_hooks_install,
    _command_hooks_installed,
    _command_hooks_list,
    _command_hooks_remove,
    _command_hooks_update,
)
from .index_cmd import (
    _add_build_index_command,
    _add_search_command,
    _command_build_index,
    _command_search,
)
from .skills import (
    _add_install_command,
    _add_list_command,
    _add_managed_commands,
    _command_install,
    _command_installed,
    _command_list,
    _command_remove,
    _command_update,
)
from .tools_cmd import (
    _add_install_tools_command,
    _add_list_tools_command,
    _command_install_tools,
    _command_list_tools,
)
from .self_update_cmd import _add_self_update_command, _command_self_update
from .workflow import _add_workflow_command, _command_workflow


def tool_version(command_name: str) -> str:
    data = tomllib.loads((project_root() / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(data["project"]["version"]).strip()
    return f"{command_name} {version}"


def maybe_print_version(argv: Sequence[str] | None, command_name: str) -> bool:
    raw = list(argv if argv is not None else sys.argv[1:])
    if raw == ["--version"]:
        print(tool_version(command_name))
        return True
    return False


def build_parser(*, prog: str = "skill-tools") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "List, install, update, and remove Agent Skills registered in ai-tools.yaml "
            "(list-skills / install-skills / ...; `install-skills self` installs the "
            "skill-tools companion skill), "
            "enumerate / install repo tools registered in repo-tools.yaml, "
            "and browse agent hooks published by repo-hooks.yaml."
        ),
        epilog=(
            "Save feedback without a subcommand: "
            "skill-tools --fb NAME [--fb-kind {skill,tool,workflow}] [--fb-text TEXT]. "
            "Omit --fb-text to read the body from stdin. "
            "--config, --source, --repo, and --github-* select the catalog the same way as "
            "list-skills."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    _add_list_command(commands)
    _add_install_command(commands)
    _add_managed_commands(commands)
    _add_list_tools_command(commands)
    _add_install_tools_command(commands)
    _add_workflow_command(commands)
    _add_hooks_command(commands)
    _add_search_command(commands)
    _add_build_index_command(commands)
    _add_config_command(commands)
    _add_self_update_command(commands)
    return parser


def run(
    args: argparse.Namespace,
    *,
    cwd: Path | None = None,
    embedder: Callable[[Sequence[str]], Sequence[Sequence[float]]] | None = None,
) -> int:
    working_directory = (cwd or Path.cwd()).resolve()
    if args.command == "list-skills":
        return _command_list(args, working_directory)
    if args.command == "install-skills":
        return _command_install(args, working_directory)
    if args.command == "installed-skills":
        return _command_installed(args, working_directory)
    if args.command == "update-skills":
        return _command_update(args, working_directory)
    if args.command == "remove-skills":
        return _command_remove(args, working_directory)
    if args.command == "list-tools":
        return _command_list_tools(args, working_directory)
    if args.command == "install-tools":
        return _command_install_tools(args, working_directory)
    if args.command == "workflow":
        return _command_workflow(args, working_directory)
    if args.command == "hooks":
        handler = {
            "list": _command_hooks_list,
            "install": _command_hooks_install,
            "installed": _command_hooks_installed,
            "update": _command_hooks_update,
            "remove": _command_hooks_remove,
        }.get(getattr(args, "hooks_command", None))
        if handler is not None:
            return handler(args, working_directory)
    if args.command == "search":
        return _command_search(args, working_directory, embedder)
    if args.command == "build-index":
        return _command_build_index(args, working_directory, embedder)
    if args.command == "self-update":
        return _command_self_update(args, working_directory)
    if args.command == "config" and getattr(args, "config_command", None) == "show":
        return _command_config_show(args, working_directory)
    if args.command == "config" and getattr(args, "config_command", None) == "init":
        return _command_config_init(args)
    raise SkillToolsError(f"unknown command: {args.command}")


def _redact_fb_text(argv: Sequence[str]) -> list[str]:
    """Hide `--fb-text` values in the copy written to the run log."""

    redacted: list[str] = []
    hide_next = False
    for arg in argv:
        if hide_next:
            redacted.append("[fb text redacted]")
            hide_next = False
            continue
        if arg == "--fb-text":
            redacted.append(arg)
            hide_next = True
            continue
        if arg.startswith("--fb-text="):
            redacted.append("--fb-text=[fb text redacted]")
            continue
        redacted.append(arg)
    return redacted


def _exit_code(exc: SkillToolsError, *, compat_search: bool = False) -> int:
    if compat_search:
        return 1
    if isinstance(exc, (CatalogError, ConfigError, IndexError)):
        return 2
    if isinstance(exc, SourceError):
        return 3
    if isinstance(exc, InstallError):
        return 4
    return 1


def _dispatch(
    parser: argparse.ArgumentParser,
    argv: Sequence[str] | None,
    *,
    cwd: Path | None = None,
    embedder: Callable[[Sequence[str]], Sequence[Sequence[float]]] | None = None,
    prog: str = "skill-tools",
    compat_search: bool = False,
) -> int:
    args = parser.parse_args(argv)
    try:
        return run(args, cwd=cwd, embedder=embedder)
    except (
        CatalogError,
        ConfigError,
        IndexError,
        SourceError,
        InstallError,
        EmbeddingError,
    ) as exc:
        print(f"{prog}: {exc}", file=sys.stderr)
        return _exit_code(exc, compat_search=compat_search)
    except SkillToolsError as exc:
        print(f"{prog}: {exc}", file=sys.stderr)
        return 1


class _Tee:
    """Mirror writes to the live stream while copying them into a buffer."""

    def __init__(self, primary, mirror) -> None:
        self._primary = primary
        self._mirror = mirror

    def write(self, data):
        self._mirror.write(data)
        return self._primary.write(data)

    def flush(self) -> None:
        self._primary.flush()
        self._mirror.flush()

    def __getattr__(self, name):
        return getattr(self._primary, name)


def _system_exit_code(exc: SystemExit) -> int:
    if isinstance(exc.code, int):
        return exc.code
    return 0 if exc.code is None else 1


def _execute(argv: Sequence[str], cwd: Path, embedder) -> int:
    if maybe_print_version(argv, "skill-tools"):
        return 0
    if fb_requested(argv):
        try:
            return execute_fb(argv, cwd)
        except SystemExit as exc:
            return _system_exit_code(exc)
        except (
            CatalogError,
            ConfigError,
            IndexError,
            SourceError,
            InstallError,
            EmbeddingError,
        ) as exc:
            print(f"skill-tools: {exc}", file=sys.stderr)
            return _exit_code(exc)
        except SkillToolsError as exc:
            print(f"skill-tools: {exc}", file=sys.stderr)
            return 1
    try:
        return _dispatch(build_parser(), argv, cwd=cwd, embedder=embedder, prog="skill-tools")
    except SystemExit as exc:
        return _system_exit_code(exc)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    embedder: Callable[[Sequence[str]], Sequence[Sequence[float]]] | None = None,
) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    working_directory = (cwd or Path.cwd()).resolve()
    session = SessionLog.from_environment()
    if session is None:
        return _execute(raw, working_directory, embedder)
    started = timestamp()
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    with (
        redirect_stdout(_Tee(sys.stdout, stdout_buffer)),
        redirect_stderr(_Tee(sys.stderr, stderr_buffer)),
    ):
        code = _execute(raw, working_directory, embedder)
    try:
        logged_stdout = stdout_buffer.getvalue()
        if raw and raw[0] == "search" and logged_stdout:
            logged_stdout = "[search output redacted]\n"
        session.record(
            argv=_redact_fb_text(raw),
            cwd=working_directory,
            started=started,
            ended=timestamp(),
            exit_code=code,
            stdout=logged_stdout,
            stderr=stderr_buffer.getvalue(),
        )
    except OSError:
        pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
