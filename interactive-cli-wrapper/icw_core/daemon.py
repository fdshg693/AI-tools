"""Background daemon for one interactive-cli-wrapper session.

Spawned detached by ``icw_cli.py``'s ``start`` command (one daemon per
session, run as ``python -m icw_core.daemon <args>`` -- never imported for
its side effects). Owns the actual :class:`icw_core.session.InteractiveSession`
so it can outlive the ``start`` CLI invocation, per the Step3 plan: an AI
agent's "one action = one CLI call" loop can't keep a process handle alive
between a `start` and a later `send`, so something has to.

Lifecycle:

1. Spawn the target command over PTY and wait for its first ready prompt
   (same ``wait_until_ready`` semantics as a normal turn).
2. Persist session metadata (:mod:`icw_core.registry`) -- including that
   first ready-wait's result -- so the ``start`` CLI invocation (polling for
   this file to appear) can hand it back to the caller as if it were a
   regular turn.
3. Serve one request at a time over local IPC (:mod:`icw_core.ipc`) until
   told to stop, or until the child process exits on its own -- either way,
   the metadata file is removed before this process exits, so a later
   ``list``/``send`` never mistakes a gone daemon for a live one.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from datetime import datetime
from multiprocessing.connection import Listener

from icw_core import registry
from icw_core.session import InteractiveSession


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="icw_core.daemon")
    parser.add_argument("--name", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument(
        "--authkey", required=True, help="Hex-encoded authkey shared with the `start` caller."
    )
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--cols", type=int, required=True)
    parser.add_argument("--idle-timeout", type=float, required=True, dest="idle_timeout")
    parser.add_argument("--overall-timeout", type=float, required=True, dest="overall_timeout")
    parser.add_argument("--ready-pattern", default=None, dest="ready_pattern")
    parser.add_argument(
        "--target-argv-json",
        required=True,
        dest="target_argv_json",
        help="JSON array: the target command + args to spawn over PTY.",
    )
    return parser.parse_args(argv)


def handle_request(session: InteractiveSession, request: dict) -> tuple[dict, bool]:
    """Returns ``(response, should_stop_serving)``."""
    action = request.get("action")

    if action == "ping":
        return {"alive": session.is_alive()}, False

    if action == "stop":
        session.close()
        return {"ok": True, "alive": session.is_alive()}, True

    if action == "send":
        try:
            result = session.send(
                request["text"],
                idle_timeout=request["idle_timeout"],
                ready_pattern=request.get("ready_pattern"),
                overall_timeout=request["overall_timeout"],
                submit_separately=request.get("submit_separately", False),
                submit_key=request.get("submit_key", "\r"),
                submit_delay=request.get("submit_delay", 0.3),
            )
        except Exception as exc:  # unexpected driver failure -- report, don't crash the daemon
            return {"error": f"{type(exc).__name__}: {exc}"}, False
        response = {
            "lines": result.lines,
            "ready": result.ready,
            "matched_pattern": result.matched_pattern,
            "elapsed_seconds": result.elapsed_seconds,
            "alive": result.alive,
        }
        # The child exited mid-turn (e.g. the user typed an exit command) --
        # nothing will ever be listening again, so stop serving and clean up
        # rather than leaving a dead session's metadata looking alive.
        return response, not result.alive

    return {"error": f"unknown action: {action!r}"}, False


def serve(session: InteractiveSession, address: str, authkey: bytes, name: str) -> None:
    listener = Listener(address, authkey=authkey)
    try:
        while True:
            conn = listener.accept()
            should_stop = False
            try:
                try:
                    request = conn.recv()
                except EOFError:
                    request = None
                if request is not None:
                    response, should_stop = handle_request(session, request)
                    try:
                        conn.send(response)
                    except OSError:
                        pass  # caller went away before we could answer -- nothing to do
            finally:
                conn.close()
            if should_stop or not session.is_alive():
                break
    finally:
        listener.close()
        registry.delete(name)
        if session.is_alive():
            session.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    target_argv = json.loads(args.target_argv_json)

    meta = registry.SessionMetadata(name=args.name)
    try:
        session = InteractiveSession(target_argv, dimensions=(args.rows, args.cols))
        result = session.wait_until_ready(
            idle_timeout=args.idle_timeout,
            ready_pattern=args.ready_pattern,
            overall_timeout=args.overall_timeout,
        )
    except Exception as exc:  # e.g. target command doesn't exist / failed to spawn
        meta.error = f"{type(exc).__name__}: {exc}"
        meta.save()
        return 1

    meta.argv = list(target_argv)
    meta.address = args.address
    meta.authkey_hex = args.authkey
    meta.pid = os.getpid()
    meta.started_at = datetime.now().isoformat()
    meta.initial_lines = result.lines
    meta.initial_ready = result.ready
    meta.initial_matched_pattern = result.matched_pattern
    meta.initial_elapsed_seconds = result.elapsed_seconds
    meta.initial_alive = result.alive
    meta.save()

    serve(session, args.address, bytes.fromhex(args.authkey), args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
