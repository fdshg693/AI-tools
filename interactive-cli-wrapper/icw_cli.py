r"""CLI entry point (``icw``): session-persisting wrapper around
:mod:`icw_core.session`, so an AI agent can drive an interactive (REPL) CLI
one Bash-tool call per turn -- ``write -> wait for the turn to settle ->
return output -> caller decides the next action`` -- without needing to keep
a process handle alive between calls.

Four subcommands, one round trip each:

    icw start --session <name> [options] -- <target command...>
    icw send --session <name> [options] "<input line>"
    icw stop --session <name>
    icw list

``start`` launches the target command's actual driver as a detached
background daemon (:mod:`icw_core.daemon`, one per session) and blocks until
that daemon reports its first ready prompt (or fails). ``send``/``stop``/
``list`` talk to a running daemon over local IPC (:mod:`icw_core.ipc`);
whenever that fails, the session is treated as dead and its metadata is
discarded (see :mod:`icw_core.registry`) rather than trusted at face value.

Validated against ``toy_repl.py`` (the test-only toy REPL fixture) and
against the real target CLI -- Cursor CLI's ``agent`` interactive mode.
See ``AGENTS.md`` for ``agent``-specific tuning notes (startup grace period,
``--submit-separately``).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import tomllib
from collections.abc import Sequence
from pathlib import Path

from icw_core import ipc, registry
from icw_core.session import DEFAULT_DIMENSIONS

# Parent dir of icw_core/ -- prepended to the spawned daemon's PYTHONPATH so
# `python -m icw_core.daemon` resolves even without an editable install of
# this package (mirrors tests/conftest.py's sys.path insertion, which only
# covers the pytest process itself, not a freshly spawned interpreter).
PACKAGE_ROOT = Path(__file__).resolve().parent

DEFAULT_IDLE_TIMEOUT = 1.0
DEFAULT_OVERALL_TIMEOUT = 30.0
DEFAULT_SUBMIT_DELAY = 0.3
# Extra time (beyond a request's own overall_timeout) the CLI waits for the
# daemon's IPC response, to cover process/IPC dispatch overhead on top of the
# driver's own wait loop.
IPC_RESPONSE_GRACE_SECONDS = 5.0
PING_TIMEOUT_SECONDS = 5.0
STOP_TIMEOUT_SECONDS = 5.0
DAEMON_POLL_INTERVAL_SECONDS = 0.2
# How much longer than the initial wait_until_ready's own overall_timeout the
# `start` CLI polls for the daemon's metadata file before giving up -- covers
# interpreter/PTY startup overhead on top of the driver's own wait loop.
DAEMON_START_GRACE_SECONDS = 10.0


def tool_version() -> str:
    data = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


def _split_target_argv(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split ``icw start --session x -- <target...>`` at the literal ``--``.

    Handled manually (not ``argparse.REMAINDER``) so option-like tokens in
    the target command (e.g. ``agent --resume``) are never mistaken for
    ``icw``'s own options.
    """
    argv = list(argv)
    if "--" in argv:
        idx = argv.index("--")
        return argv[:idx], argv[idx + 1 :]
    return argv, []


def _print_turn(result: dict) -> None:
    for line in result.get("lines") or []:
        print(line)
    elapsed = result.get("elapsed_seconds")
    elapsed_str = f"{elapsed:.2f}s" if elapsed is not None else "?"
    print(
        f"[ready={result.get('ready')} alive={result.get('alive')} "
        f"matched_pattern={result.get('matched_pattern')} elapsed={elapsed_str}]",
        file=sys.stderr,
    )


def _check_alive(meta: registry.SessionMetadata) -> bool:
    if meta.address is None or meta.authkey_hex is None:
        return False
    try:
        response = ipc.call(
            meta.address, meta.authkey, {"action": "ping"}, timeout=PING_TIMEOUT_SECONDS
        )
    except Exception:
        return False
    return bool(response.get("alive"))


def cmd_start(args: argparse.Namespace, target_argv: list[str]) -> int:
    if not target_argv:
        print("error: `start` requires a target command after `--`", file=sys.stderr)
        return 1

    existing = registry.load_if_exists(args.session)
    if existing is not None:
        if _check_alive(existing):
            print(
                f"error: session {args.session!r} already running (pid={existing.pid})",
                file=sys.stderr,
            )
            return 1
        registry.delete(args.session)  # stale metadata from a crashed/killed daemon

    address = ipc.session_address(args.session)
    authkey = ipc.new_authkey()
    daemon_argv = [
        sys.executable,
        "-u",
        "-m",
        "icw_core.daemon",
        "--name",
        args.session,
        "--address",
        address,
        "--authkey",
        authkey.hex(),
        "--rows",
        str(args.rows),
        "--cols",
        str(args.cols),
        "--idle-timeout",
        str(args.idle_timeout),
        "--overall-timeout",
        str(args.overall_timeout),
        "--target-argv-json",
        json.dumps(target_argv),
    ]
    if args.ready_pattern:
        daemon_argv += ["--ready-pattern", args.ready_pattern]

    _spawn_detached(daemon_argv)

    deadline = time.monotonic() + args.overall_timeout + DAEMON_START_GRACE_SECONDS
    meta = None
    while time.monotonic() < deadline:
        meta = registry.load_if_exists(args.session)
        if meta is not None:
            break
        time.sleep(DAEMON_POLL_INTERVAL_SECONDS)

    if meta is None:
        print(f"error: session {args.session!r} did not become ready in time", file=sys.stderr)
        return 1
    if meta.error:
        registry.delete(args.session)
        print(f"error: failed to start session {args.session!r}: {meta.error}", file=sys.stderr)
        return 1

    _print_turn(
        {
            "lines": meta.initial_lines,
            "ready": meta.initial_ready,
            "matched_pattern": meta.initial_matched_pattern,
            "elapsed_seconds": meta.initial_elapsed_seconds,
            "alive": meta.initial_alive,
        }
    )
    return 0 if meta.initial_ready else 1


def _spawn_detached(argv: list[str]) -> None:
    """Launch ``argv`` as a process that fully outlives this one (same
    approach as ``tav_core.run_shell.spawn_detached``: on Windows,
    ``DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP``; on POSIX, a new
    session). The daemon's std streams are detached -- it talks to no one
    directly, only over the IPC channel set up in its own argv."""
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{PACKAGE_ROOT}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(PACKAGE_ROOT)
    )
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "env": env,
    }
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, **kwargs)  # noqa: S603 - argv is built internally, not from shell input


def cmd_send(args: argparse.Namespace) -> int:
    meta = registry.load_if_exists(args.session)
    if meta is None:
        print(f"error: no such session {args.session!r}", file=sys.stderr)
        return 1

    request = {
        "action": "send",
        "text": args.text,
        "idle_timeout": args.idle_timeout,
        "ready_pattern": args.ready_pattern,
        "overall_timeout": args.overall_timeout,
        "submit_separately": args.submit_separately,
        "submit_key": args.submit_key,
        "submit_delay": args.submit_delay,
    }
    try:
        response = ipc.call(
            meta.address,
            meta.authkey,
            request,
            timeout=args.overall_timeout + IPC_RESPONSE_GRACE_SECONDS,
        )
    except Exception as exc:
        registry.delete(args.session)
        print(
            f"error: session {args.session!r} is not alive ({exc}); stale metadata removed",
            file=sys.stderr,
        )
        return 1

    if "error" in response:
        print(f"error: {response['error']}", file=sys.stderr)
        return 1

    _print_turn(response)
    if not response.get("alive", False):
        registry.delete(args.session)
    return 0 if response.get("ready") else 1


def cmd_stop(args: argparse.Namespace) -> int:
    meta = registry.load_if_exists(args.session)
    if meta is None:
        print(f"session {args.session!r} is not running (no metadata)", file=sys.stderr)
        return 0

    try:
        ipc.call(meta.address, meta.authkey, {"action": "stop"}, timeout=STOP_TIMEOUT_SECONDS)
    except Exception:
        pass  # already dead -- fall through to metadata cleanup either way
    registry.delete(args.session)
    print(f"stopped session {args.session!r}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    names = registry.list_names()
    if not names:
        print("no sessions")
        return 0
    for name in names:
        meta = registry.load_if_exists(name)
        if meta is None:
            continue
        alive = _check_alive(meta)
        if not alive:
            registry.delete(name)
        status = "alive" if alive else "dead (metadata removed)"
        print(f"{name}: {status} argv={meta.argv} pid={meta.pid} started_at={meta.started_at}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="icw",
        description="Session-persisting wrapper around a PTY-driven interactive CLI "
        "(start/send/stop/list), one Bash-tool call per turn.",
    )
    parser.add_argument("--version", action="version", version=f"icw {tool_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_start = subparsers.add_parser(
        "start", help="Start a new session as a detached background daemon."
    )
    p_start.add_argument("--session", required=True, help="Session name, used to address it later.")
    p_start.add_argument("--rows", type=int, default=DEFAULT_DIMENSIONS[0])
    p_start.add_argument("--cols", type=int, default=DEFAULT_DIMENSIONS[1])
    p_start.add_argument("--idle-timeout", type=float, default=DEFAULT_IDLE_TIMEOUT)
    p_start.add_argument("--overall-timeout", type=float, default=DEFAULT_OVERALL_TIMEOUT)
    p_start.add_argument(
        "--ready-pattern", default=None, help="Regex checked against the initial screen."
    )
    p_start.set_defaults(needs_target=True)

    p_send = subparsers.add_parser(
        "send", help="Write one line of input to a running session and wait for the turn to settle."
    )
    p_send.add_argument("--session", required=True)
    p_send.add_argument(
        "text", help="Input line to submit (a trailing newline is added if missing)."
    )
    p_send.add_argument("--idle-timeout", type=float, default=DEFAULT_IDLE_TIMEOUT)
    p_send.add_argument("--overall-timeout", type=float, default=DEFAULT_OVERALL_TIMEOUT)
    p_send.add_argument("--ready-pattern", default=None)
    p_send.add_argument(
        "--submit-separately",
        action="store_true",
        help="Write the input text and the submit key as two separate writes "
        "instead of one combined write. Needed for real TUIs that treat a "
        "single write containing an embedded newline as a pasted block "
        "rather than 'type then press Enter' (e.g. Cursor CLI's `agent` -- "
        "see tools/interactive-cli-wrapper/AGENTS.md).",
    )
    p_send.add_argument(
        "--submit-key",
        default="\r",
        help="Key sequence written as the separate 'Enter' when "
        "--submit-separately is set (default: bare CR, not CRLF).",
    )
    p_send.add_argument(
        "--submit-delay",
        type=float,
        default=DEFAULT_SUBMIT_DELAY,
        help="Seconds to wait between the text write and the --submit-key write "
        "when --submit-separately is set.",
    )
    p_send.set_defaults(func=cmd_send, needs_target=False)

    p_stop = subparsers.add_parser("stop", help="Stop a running session.")
    p_stop.add_argument("--session", required=True)
    p_stop.set_defaults(func=cmd_stop, needs_target=False)

    p_list = subparsers.add_parser(
        "list", help="List known sessions and whether each is still alive."
    )
    p_list.set_defaults(func=cmd_list, needs_target=False)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else list(argv)
    wrapper_argv, target_argv = _split_target_argv(raw)

    parser = build_parser()
    args = parser.parse_args(wrapper_argv)

    if target_argv and not args.needs_target:
        print(f"error: `{args.command}` does not take a `-- <command>` suffix", file=sys.stderr)
        return 1

    if args.command == "start":
        return cmd_start(args, target_argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
