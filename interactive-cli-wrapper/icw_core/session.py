"""PTY-driven core driver: spawn an interactive (REPL) CLI, send it one line
of input, and wait for it to settle back into "waiting for the next input"
before handing the current screen back to the caller.

This is the "one turn" primitive the rest of the wrapper (session
persistence + CLI in later steps) is built on: write -> wait for the turn to
settle -> return output -> caller decides the next action.

Built on ``winpty.PtyProcess`` (ConPTY-backed pseudo-console spawning) and
:class:`icw_core.screen.TerminalScreen` (ANSI reconstruction). See
``README.md``'s "なぜPTY駆動が必要か" section for why raw subprocess pipes and
the ``winpty`` CLI don't work here instead.
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from re import Pattern

from winpty import PtyProcess

from icw_core.screen import TerminalScreen

DEFAULT_DIMENSIONS = (40, 120)  # (rows, columns), matches the Step1 research probes
DEFAULT_READ_CHUNK_BYTES = 65536
# How often the read loop polls the PTY's underlying socket for new bytes.
# ``PtyProcess.read`` is otherwise a blocking call (see module docstring in
# icw_core.screen and the Step1 research notes) -- this timeout is what turns
# it into a pollable one.
DEFAULT_READ_POLL_SECONDS = 0.2


@dataclass(slots=True)
class ReadyResult:
    """Outcome of waiting for a turn to settle.

    ``ready`` is True once the driver considers the CLI "back at the input
    prompt": either ``ready_pattern`` matched the current screen, or the
    screen went unchanged for ``idle_timeout`` seconds (the idle-timeout
    baseline is always active; the pattern is an optional, faster/more
    precise signal layered on top -- see the Step2 plan's decision table).
    ``ready`` is False only when ``overall_timeout`` was hit with neither
    signal firing -- the caller decides whether to keep waiting or give up.
    """

    lines: list[str]
    ready: bool
    matched_pattern: bool
    elapsed_seconds: float
    alive: bool


class InteractiveSession:
    """One spawned interactive CLI process, driven turn by turn."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        dimensions: tuple[int, int] = DEFAULT_DIMENSIONS,
        read_chunk_bytes: int = DEFAULT_READ_CHUNK_BYTES,
        read_poll_seconds: float = DEFAULT_READ_POLL_SECONDS,
    ) -> None:
        rows, columns = dimensions
        self._proc = PtyProcess.spawn(list(argv), dimensions=(rows, columns))
        self._proc.fileobj.settimeout(read_poll_seconds)
        self._screen = TerminalScreen(columns=columns, rows=rows)
        self._read_chunk_bytes = read_chunk_bytes

    def is_alive(self) -> bool:
        return self._proc.isalive()

    @property
    def exit_status(self) -> int | None:
        return self._proc.exitstatus if not self.is_alive() else None

    def snapshot(self) -> list[str]:
        return self._screen.snapshot()

    def write(self, text: str) -> None:
        """Write raw text as-is (no newline normalization)."""
        self._proc.write(text)

    def _drain_once(self) -> tuple[bool, bool]:
        """Try reading one chunk. Returns ``(got_data, alive)``."""
        try:
            data = self._proc.read(self._read_chunk_bytes)
        except EOFError:
            return False, False
        except OSError:
            # The per-read timeout elapsed with nothing to read yet -- not an
            # error, just "poll again".
            return False, self.is_alive()
        if data:
            self._screen.feed(data)
        return bool(data), self.is_alive()

    def wait_until_ready(
        self,
        *,
        idle_timeout: float,
        ready_pattern: Pattern[str] | str | None = None,
        overall_timeout: float = 30.0,
    ) -> ReadyResult:
        """Poll until the CLI looks like it's back waiting for input.

        ``idle_timeout`` (seconds of no new output) is the mandatory
        baseline. ``ready_pattern`` (matched against the current screen,
        newline-joined) is an optional faster/more precise signal -- when it
        matches, the driver doesn't wait out the rest of ``idle_timeout``.
        Returns as soon as either fires, the process exits, or
        ``overall_timeout`` elapses (``ready=False`` in that last case).
        """
        pattern = re.compile(ready_pattern) if isinstance(ready_pattern, str) else ready_pattern

        start = time.monotonic()
        last_change = start
        current = self.snapshot()

        while True:
            got_data, alive = self._drain_once()
            now = time.monotonic()
            if got_data:
                last_change = now
                current = self.snapshot()

            if not alive:
                # Nothing more will ever arrive -- no point waiting further.
                return ReadyResult(
                    lines=current,
                    ready=True,
                    matched_pattern=False,
                    elapsed_seconds=now - start,
                    alive=False,
                )

            matched_pattern = pattern is not None and pattern.search("\n".join(current)) is not None
            idle_elapsed = now - last_change
            if matched_pattern or idle_elapsed >= idle_timeout:
                return ReadyResult(
                    lines=current,
                    ready=True,
                    matched_pattern=matched_pattern,
                    elapsed_seconds=now - start,
                    alive=True,
                )

            if now - start >= overall_timeout:
                return ReadyResult(
                    lines=current,
                    ready=False,
                    matched_pattern=False,
                    elapsed_seconds=now - start,
                    alive=True,
                )

    def send(
        self,
        text: str,
        *,
        idle_timeout: float,
        ready_pattern: Pattern[str] | str | None = None,
        overall_timeout: float = 30.0,
        submit_separately: bool = False,
        submit_key: str = "\r",
        submit_delay: float = 0.3,
    ) -> ReadyResult:
        """One full turn: submit one line of input, wait for it to settle.

        By default, appends ``\\r\\n`` to ``text`` and writes it in a single
        ``write()`` call when it doesn't already end in a newline -- Windows
        console input needs CRLF to submit a line (see the Step1 research
        notes' ``cmd.exe`` probe), and this is what the toy CLI (and any
        line-buffered-stdin target) expects.

        Some real interactive TUIs (e.g. Cursor CLI's ``agent`` -- see
        ``README.md``'s "`agent`対話モードへの接続で判明した癖" section)
        run their own raw-keypress input handling and treat a single write
        containing embedded newline bytes as a multi-line paste (inserting a
        literal newline instead of submitting), regardless of gap length
        between the text and the newline *within that same write*. For
        those, pass ``submit_separately=True`` so the text and ``submit_key``
        go out as two distinct ``write()`` calls with ``submit_delay``
        seconds between them -- enough for the target's input handler to see
        them as separate keypress events rather than one pasted blob.
        """
        if submit_separately:
            self.write(text)
            time.sleep(submit_delay)
            self.write(submit_key)
        else:
            if not text.endswith(("\r\n", "\n")):
                text = f"{text}\r\n"
            self.write(text)
        return self.wait_until_ready(
            idle_timeout=idle_timeout, ready_pattern=ready_pattern, overall_timeout=overall_timeout
        )

    def close(self, *, force_after: float = 2.0) -> None:
        """Best-effort shutdown: try Ctrl-C first, then force-terminate."""
        if not self.is_alive():
            return
        self._proc.sendintr()
        deadline = time.monotonic() + force_after
        while self.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        if self.is_alive():
            self._proc.terminate(force=True)
