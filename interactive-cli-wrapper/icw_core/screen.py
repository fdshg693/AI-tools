"""Terminal screen emulation: turns raw ANSI-laden bytes from a PTY into a
stable text snapshot.

Interactive TUIs redraw the same lines via cursor repositioning (and
sometimes OSC title sequences), so stripping ANSI escapes with a regex would
leave duplicated or garbled text. Feeding the raw bytes into a ``pyte``
screen buffer instead reconstructs "what the terminal currently shows",
which is what :class:`icw_core.session.InteractiveSession` bases both output
and "back at the input prompt" detection on. Confirmed stable against a real
captured ConPTY session (cursor moves + OSC title + mode toggles) -- see the
fixture bytes exercised in ``tests/test_screen.py``.
"""

from __future__ import annotations

import pyte


class TerminalScreen:
    """A ``pyte`` screen buffer, exposing only what the driver needs: feed
    bytes in, read the current non-blank display lines out."""

    def __init__(self, *, columns: int, rows: int) -> None:
        self._screen = pyte.Screen(columns, rows)
        self._stream = pyte.Stream(self._screen)

    def feed(self, data: str) -> None:
        self._stream.feed(data)

    def snapshot(self) -> list[str]:
        """Current screen content as a list of lines, trailing blank lines
        stripped (their count only reflects unused screen rows, not output)."""
        lines = [line.rstrip() for line in self._screen.display]
        while lines and not lines[-1]:
            lines.pop()
        return lines
