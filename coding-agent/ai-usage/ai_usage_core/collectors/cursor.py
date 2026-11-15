"""Cursor usage collector: unlike Claude Code/Codex, `cursor-agent` (Cursor's
CLI) has no pull API or JSON output for usage -- `/usage` only exists as a
slash command inside the interactive TUI, and the TUI is an Ink app that
renders full-screen (and behaves differently, if it runs at all) without a
real terminal attached. So this drives it through an actual Windows
pseudo-console (ConPTY via `pywinpty`) instead of plain subprocess pipes:
launch `cursor-agent --trust`, wait for the prompt, type `/usage`, wait for
the dropdown, press Enter, wait for the response to render, then replay the
captured ANSI stream through a virtual terminal (`pyte`) and return its
final screen contents.

`--trust` is passed so a first run in a new workspace doesn't hang forever
on a "do you trust this directory" prompt with nobody there to answer it.

Because this is a full screen dump rather than parsed windows/percentages,
it's surfaced separately by the CLI (see `--cursor` in ai_usage_cli.py)
rather than folded into render_table()'s tool/window/used/resets columns.
It's opt-in and slow (real process boot + a fixed wait for rendering, tens
of seconds) compared to the other collectors, which is why it isn't part of
the default `show` output.
"""

from __future__ import annotations

import queue
import shutil
import threading
import time

_CMD_NAME = "cursor-agent"
_STARTUP_WAIT_SECONDS = 10.0
_DROPDOWN_WAIT_SECONDS = 2.5
_RESPONSE_WAIT_SECONDS = 10.0
_SCREEN_COLS = 120
_SCREEN_ROWS = 50
# Heuristic markers for "the /usage panel actually rendered" vs. "the
# slash-command dropdown is still open" -- Enter racing the dropdown's fuzzy
# match settling is the observed failure mode, so on a miss we retry Enter
# once rather than returning a screenshot of an unopened menu.
_DROPDOWN_MARKER = "Show plan and on-demand usage"
_PANEL_MARKER = "Esc to close"


class _PtySession:
    """A `cursor-agent` process on a real pseudo-console, with a background
    reader thread -- PtyProcess.read() blocks with no timeout, so draining
    with a deadline needs to happen off a queue rather than by calling
    read() directly from the polling loop.
    """

    def __init__(self, argv: list[str]) -> None:
        from winpty import PtyProcess

        self._pty = PtyProcess.spawn(argv, dimensions=(_SCREEN_ROWS, _SCREEN_COLS))
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        try:
            while True:
                data = self._pty.read(65536)
                if not data:
                    break
                self._queue.put(data)
        except EOFError:
            pass
        except Exception:
            pass
        finally:
            self._queue.put(None)

    def write(self, s: str) -> None:
        self._pty.write(s)

    def drain(self, seconds: float) -> str:
        """Collect whatever output arrives over a fixed wall-clock window.

        This is deliberately a plain fixed wait rather than an early-exit-on-
        idle optimization: the TUI's rendering has enough natural pauses
        (e.g. between the dropdown appearing and its fuzzy match settling)
        that idle-based cutoffs raced ahead of the actual UI state in
        testing and sent Enter before the dropdown had finished settling.
        """
        chunks = []
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                item = self._queue.get(timeout=remaining)
            except queue.Empty:
                break
            if item is None:
                break
            chunks.append(item)
        return "".join(chunks)

    def close(self) -> None:
        try:
            self._pty.close(force=True)
        except Exception:
            pass


def _render_final_screen(raw: str) -> str:
    import pyte

    screen = pyte.Screen(_SCREEN_COLS, _SCREEN_ROWS)
    pyte.Stream(screen).feed(raw)
    lines = [line.rstrip() for line in screen.display]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def collect_raw() -> str | None:
    """Return a plain-text snapshot of the `/usage` screen, or None if
    `cursor-agent` isn't installed or the required PTY/terminal-emulation
    dependencies (`pywinpty`, `pyte`) aren't available.
    """
    if shutil.which(_CMD_NAME) is None:
        return None

    try:
        import pyte  # noqa: F401
        from winpty import PtyProcess  # noqa: F401
    except ImportError:
        return None

    session = _PtySession([_CMD_NAME, "--trust"])
    try:
        raw = session.drain(_STARTUP_WAIT_SECONDS)
        session.write("/usage")
        raw += session.drain(_DROPDOWN_WAIT_SECONDS)
        session.write("\r")
        raw += session.drain(_RESPONSE_WAIT_SECONDS)

        text = _render_final_screen(raw)
        if _DROPDOWN_MARKER in text and _PANEL_MARKER not in text:
            # Enter raced the dropdown's fuzzy match settling; try once more.
            session.write("\r")
            raw += session.drain(_RESPONSE_WAIT_SECONDS)
            text = _render_final_screen(raw)
    finally:
        session.close()

    return text or None
