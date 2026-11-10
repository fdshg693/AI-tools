"""PTY driver tests against the toy REPL (``toy_repl.py``): single-turn
round trip, multiple consecutive turns, and the core risk called out in the
Step2 plan -- that idle-timeout detection must not mistake a mid-turn output
gap for "back at the prompt".

Windows-only: ``pywinpty``/ConPTY has no non-Windows backend.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from icw_core.session import InteractiveSession
from toy_repl import READY_PROMPT

# icw_core.screen.TerminalScreen.rstrip()s every line (unused screen columns
# are indistinguishable from a real trailing space), so matching against the
# prompt's own trailing space would never hit. Match the stripped form.
READY_PROMPT_STRIPPED = READY_PROMPT.strip()
READY_PATTERN = re.compile(re.escape(READY_PROMPT_STRIPPED) + r"$")

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="pywinpty is Windows-only (ConPTY)")

TOY_REPL_PATH = Path(__file__).resolve().parent.parent / "toy_repl.py"

# Cold Python interpreter startup under a fresh ConPTY was observed (on this
# machine, during Step2 development) to consistently take ~3s before the
# child's own first print() becomes visible at all -- an idle_timeout below
# that would misdetect "ready" during the gap, based on nothing having
# changed yet rather than the CLI actually settling (the exact risk flagged
# in the Step2 plan's decision table -- reproduced here by our own fixture,
# not just a hypothetical about slow real CLIs). ready_pattern make startup
# detection resolve close to the real ~3s latency instead of waiting out the
# full idle_timeout; overall_timeout stays generous as the safety net.
STARTUP_IDLE_TIMEOUT = 6.0
STARTUP_TIMEOUT = 30.0


def spawn_toy(**toy_args: str) -> InteractiveSession:
    argv = [sys.executable, "-u", str(TOY_REPL_PATH)]
    for name, value in toy_args.items():
        argv.append(f"--{name.replace('_', '-')}")
        argv.append(str(value))
    session = InteractiveSession(argv)
    session.wait_until_ready(
        idle_timeout=STARTUP_IDLE_TIMEOUT,
        ready_pattern=READY_PATTERN,
        overall_timeout=STARTUP_TIMEOUT,
    )
    return session


@pytest.fixture
def toy() -> InteractiveSession:
    session = spawn_toy()
    yield session
    session.close()


def test_startup_reaches_ready_prompt(toy: InteractiveSession) -> None:
    assert any(READY_PROMPT_STRIPPED in line for line in toy.snapshot())
    assert toy.is_alive()


def test_single_turn_round_trip(toy: InteractiveSession) -> None:
    result = toy.send("hello", idle_timeout=1.0, overall_timeout=10.0)

    assert result.ready
    assert result.alive
    assert any("echo[0]: hello" in line for line in result.lines)
    assert any(READY_PROMPT_STRIPPED in line for line in result.lines)


def test_multiple_consecutive_turns_round_trip(toy: InteractiveSession) -> None:
    for message in ("first", "second", "third"):
        result = toy.send(message, idle_timeout=1.0, overall_timeout=10.0)
        assert result.ready
        assert any(f"echo[0]: {message}" in line for line in result.lines)
    assert toy.is_alive()


def test_trickling_output_is_not_misdetected_as_ready() -> None:
    """Each of the 4 echo lines arrives 0.3s apart (idle_timeout=1.0s, so no
    single gap trips it). The result must contain every chunk and take at
    least as long as the trickle itself -- proving the driver waited through
    every gap instead of returning after the first quiet moment.
    """
    chunk_delay = 0.3
    chunks = 4
    trickly = spawn_toy(chunk_delay=chunk_delay, chunks_per_turn=chunks)
    try:
        result = trickly.send("go", idle_timeout=1.0, overall_timeout=10.0)

        assert result.ready
        for i in range(chunks):
            assert any(f"echo[{i}]: go" in line for line in result.lines), (
                f"chunk {i} missing -- looks like idle-timeout fired mid-turn"
            )
        assert result.elapsed_seconds >= chunk_delay * chunks * 0.8
    finally:
        trickly.close()


def test_ready_pattern_short_circuits_idle_timeout(toy: InteractiveSession) -> None:
    """With a ready_pattern that matches the toy's prompt, the driver should
    return quickly even when idle_timeout is set far longer than the actual
    turn takes -- proving the pattern is checked as a faster alternative to
    waiting out the idle baseline, not just after it.
    """
    result = toy.send("quick", idle_timeout=5.0, ready_pattern=READY_PATTERN, overall_timeout=10.0)

    assert result.ready
    assert result.matched_pattern
    assert result.elapsed_seconds < 1.0


def test_close_terminates_the_process(toy: InteractiveSession) -> None:
    toy.close()
    assert not toy.is_alive()
