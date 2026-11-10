"""Offline test for ``icw_core.screen.TerminalScreen``: feed it real
ANSI-laden bytes (captured from a live ConPTY ``cmd.exe`` session during
Step1 research -- cursor repositioning, an OSC title sequence, and mode
toggles) and check the reconstructed snapshot is clean, not garbled or
duplicated. No process spawned, no PTY involved -- this isolates the
trickiest part (ANSI reconstruction) from the platform-specific spawning
machinery covered by ``test_session.py``.
"""

from __future__ import annotations

from icw_core.screen import TerminalScreen

# Verbatim from temp/interactive-cli-wrapper-research/02_pyte_eval.py, itself
# captured from 01_pywinpty_smoke.py's "after echo" output.
RAW = (
    "\x1b[?7l\x1b[?7hMicrosoft Windows [Version 10.0.26200.8875]\r\n"
    "(c) Microsoft Corporation. All rights reserved.\r\n\r\n"
    "C:\\CodeRoot\\AI\\temp\\interactive-cli-wrapper-research>"
    "\x1b[4;54Hecho HELLO_FROM_PTY\x1b[4;73H\r\n"
    "\x1b]0;C:\\Windows\\system32\\cmd.exe - echo  HELLO_FROM_PTY\x1b\\"
    "HELLO_FROM_PTY\r\n"
    "\x1b]0;C:\\Windows\\system32\\cmd.exe\x1b\\\r\n"
    "C:\\CodeRoot\\AI\\temp\\interactive-cli-wrapper-research>"
)


def test_snapshot_reconstructs_clean_lines_from_ansi_bytes() -> None:
    screen = TerminalScreen(columns=100, rows=30)
    screen.feed(RAW)

    lines = screen.snapshot()

    assert "Microsoft Windows [Version 10.0.26200.8875]" in lines[0]
    # The echoed command shares its row with the prompt (cursor was
    # repositioned mid-line, not moved to a new one) -- that's the terminal
    # faithfully reproducing a single redrawn row, not garbling.
    assert any(line.endswith("echo HELLO_FROM_PTY") for line in lines)
    assert any(line.strip() == "HELLO_FROM_PTY" for line in lines)
    # No duplication/garbling: each distinct piece of text appears exactly once.
    assert sum(1 for line in lines if line.strip() == "HELLO_FROM_PTY") == 1


def test_snapshot_strips_trailing_blank_rows_only() -> None:
    screen = TerminalScreen(columns=20, rows=10)
    screen.feed("line one\r\nline two\r\n")

    lines = screen.snapshot()

    assert lines[-1].strip() == "line two"
    assert len(lines) == 2


def test_snapshot_is_idempotent_without_new_feed() -> None:
    screen = TerminalScreen(columns=20, rows=10)
    screen.feed("stable\r\n")

    assert screen.snapshot() == screen.snapshot()
