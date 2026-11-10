"""Integration tests for the session-persisting `icw` CLI (start/send/stop/
list), against the toy REPL (``toy_repl.py``) -- real CLI (``agent``)
integration is Step4, per the Step3 plan.

Each test drives ``icw_cli.main()`` directly (in-process), the same way an
AI agent would invoke ``icw`` once per Bash-tool call: every call here spawns
a *detached* daemon subprocess (for `start`) or talks to one over local IPC
(for `send`/`stop`/`list`) and returns, exactly like a separate process
invocation would -- nothing is held open across calls within a test.

Windows-only: ``pywinpty``/ConPTY has no non-Windows backend (same
constraint as test_session.py).
"""

from __future__ import annotations

import re
import sys
import time
import uuid
from pathlib import Path

import pytest

import icw_cli
from icw_core import registry

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="pywinpty is Windows-only (ConPTY)")

TOY_REPL_PATH = Path(__file__).resolve().parent.parent / "toy_repl.py"
READY_PROMPT_STRIPPED = "toy>"
READY_PATTERN = re.escape(READY_PROMPT_STRIPPED) + r"$"

# Cold Python interpreter startup under a fresh ConPTY takes a few seconds
# before the toy REPL's own banner is visible (see test_session.py's
# STARTUP_IDLE_TIMEOUT comment) -- generous enough for `start`'s daemon
# subprocess (its own separate interpreter) to reach the same point.
STARTUP_IDLE_TIMEOUT = 6.0
STARTUP_OVERALL_TIMEOUT = 30.0
TURN_IDLE_TIMEOUT = 1.0
TURN_OVERALL_TIMEOUT = 10.0


@pytest.fixture
def session_name() -> str:
    name = f"pytest-icw-{uuid.uuid4().hex[:8]}"
    yield name
    # Best-effort cleanup: if an assertion failed mid-test, don't leave a
    # detached daemon running past this test.
    icw_cli.main(["stop", "--session", name])


def start_toy_session(name: str) -> int:
    return icw_cli.main(
        [
            "start",
            "--session",
            name,
            "--idle-timeout",
            str(STARTUP_IDLE_TIMEOUT),
            "--overall-timeout",
            str(STARTUP_OVERALL_TIMEOUT),
            "--ready-pattern",
            READY_PATTERN,
            "--",
            sys.executable,
            "-u",
            str(TOY_REPL_PATH),
        ]
    )


def send_to_toy(name: str, text: str) -> int:
    return icw_cli.main(
        [
            "send",
            "--session",
            name,
            "--idle-timeout",
            str(TURN_IDLE_TIMEOUT),
            "--overall-timeout",
            str(TURN_OVERALL_TIMEOUT),
            text,
        ]
    )


def test_start_reaches_ready_prompt(session_name: str, capsys: pytest.CaptureFixture) -> None:
    exit_code = start_toy_session(session_name)
    captured = capsys.readouterr()

    assert exit_code == 0
    assert READY_PROMPT_STRIPPED in captured.out
    meta = registry.load_if_exists(session_name)
    assert meta is not None
    assert meta.initial_ready is True
    assert meta.initial_alive is True


def test_send_multiple_consecutive_turns(session_name: str, capsys: pytest.CaptureFixture) -> None:
    assert start_toy_session(session_name) == 0
    capsys.readouterr()  # discard `start`'s own output

    for message in ("first", "second", "third"):
        exit_code = send_to_toy(session_name, message)
        captured = capsys.readouterr()
        assert exit_code == 0
        assert f"echo[0]: {message}" in captured.out


def test_stop_then_send_fails(session_name: str, capsys: pytest.CaptureFixture) -> None:
    assert start_toy_session(session_name) == 0
    capsys.readouterr()

    stop_exit_code = icw_cli.main(["stop", "--session", session_name])
    assert stop_exit_code == 0
    assert registry.load_if_exists(session_name) is None

    exit_code = send_to_toy(session_name, "hello")
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "no such session" in captured.err


def test_child_exit_cleans_up_metadata(session_name: str, capsys: pytest.CaptureFixture) -> None:
    """Sending "exit" makes the toy REPL end its own loop (not `stop`) --
    the daemon should notice the child died and clean up metadata itself,
    exactly like an explicit `stop` would, per the Step3 plan's decision on
    IPC-connection-based liveness (a dead child must not look alive)."""
    assert start_toy_session(session_name) == 0
    capsys.readouterr()

    exit_code = send_to_toy(session_name, "exit")
    captured = capsys.readouterr()
    # wait_until_ready treats "the process ended" as ready=True (nothing more
    # will ever arrive) -- alive=False is the signal that it exited instead
    # of settling back at the prompt.
    assert exit_code == 0
    assert "alive=False" in captured.err

    # Give the now-dying daemon a moment to finish its own cleanup
    # (registry.delete happens after the response is already sent back).
    deadline = time.monotonic() + 5.0
    while registry.load_if_exists(session_name) is not None and time.monotonic() < deadline:
        time.sleep(0.1)
    assert registry.load_if_exists(session_name) is None


def test_list_reports_alive_then_removes_after_stop(
    session_name: str, capsys: pytest.CaptureFixture
) -> None:
    assert start_toy_session(session_name) == 0
    capsys.readouterr()

    icw_cli.main(["list"])
    captured = capsys.readouterr()
    assert f"{session_name}: alive" in captured.out

    icw_cli.main(["stop", "--session", session_name])
    capsys.readouterr()

    icw_cli.main(["list"])
    captured = capsys.readouterr()
    assert session_name not in captured.out
