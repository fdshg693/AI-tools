"""Append-only session logs for skill-tools CLI invocations.

Every invocation appends one input item (arguments and working directory) and
one output item (stdout, stderr, exit code). The two items share a sequential
``run`` marker and live in paired files with the same number, so an input can
be matched to its output when needed while the input log stays the natural
thing to skim.

Files rotate on size alone and only at item boundaries, so an item is never
split across files. A single item larger than the threshold is written whole.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..locations import project_root

LOG_DIR_ENV = "SKILL_TOOLS_LOG_DIR"
LOG_MAX_BYTES_ENV = "SKILL_TOOLS_LOG_MAX_BYTES"
LOG_DISABLE_ENV = "SKILL_TOOLS_LOG_DISABLE"
DEFAULT_MAX_BYTES = 1_000_000
DISABLED_VALUES = {"1", "true", "yes", "on"}
STATE_FILE = ".state.json"
FILE_PATTERN = re.compile(r"^(\d+)\.log$")
INPUT_DIR = "input"
OUTPUT_DIR = "output"


def default_log_dir() -> Path:
    """Resolve the log directory next to the installed skill_tools package."""

    override = os.environ.get(LOG_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return project_root() / "logs"


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _format_input(run: int, started: str, cwd: Path, argv: Sequence[str]) -> str:
    return (
        f"===== run {run:06d} | {started} =====\n"
        f"cwd: {cwd}\n"
        f"argv: {json.dumps(list(argv), ensure_ascii=False)}\n\n"
    )


def _format_block(label: str, value: str) -> str:
    body = value.rstrip("\n")
    if not body:
        return f"[{label}]\n(empty)"
    return f"[{label}]\n{body}"


def _format_output(run: int, ended: str, exit_code: int, stdout: str, stderr: str) -> str:
    return (
        f"===== run {run:06d} | {ended} | exit {exit_code} =====\n"
        f"{_format_block('stdout', stdout)}\n"
        f"{_format_block('stderr', stderr)}\n\n"
    )


def _byte_length(text: str) -> int:
    return len(text.encode("utf-8"))


def _overflows(path: Path, item: str, max_bytes: int) -> bool:
    try:
        current = path.stat().st_size
    except OSError:
        return False
    if current <= 0:
        return False
    return current + _byte_length(item) > max_bytes


def _append(path: Path, item: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(item)


@dataclass(frozen=True)
class SessionLog:
    """Append paired input/output items to a rotating log directory."""

    directory: Path
    max_bytes: int = DEFAULT_MAX_BYTES

    @classmethod
    def from_environment(cls) -> SessionLog | None:
        disabled = os.environ.get(LOG_DISABLE_ENV, "").strip().lower()
        if disabled in DISABLED_VALUES:
            return None
        max_bytes = DEFAULT_MAX_BYTES
        raw_max = os.environ.get(LOG_MAX_BYTES_ENV, "").strip()
        if raw_max:
            try:
                max_bytes = max(1, int(raw_max))
            except ValueError:
                max_bytes = DEFAULT_MAX_BYTES
        return cls(directory=default_log_dir(), max_bytes=max_bytes)

    def record(
        self,
        *,
        argv: Sequence[str],
        cwd: Path,
        started: str,
        ended: str,
        exit_code: int,
        stdout: str,
        stderr: str,
    ) -> None:
        state = self._read_state()
        run = int(state.get("run", 0)) + 1
        pair = self._current_pair(state)
        input_item = _format_input(run, started, cwd, argv)
        output_item = _format_output(run, ended, exit_code, stdout, stderr)
        input_path = self._item_path(INPUT_DIR, pair)
        output_path = self._item_path(OUTPUT_DIR, pair)
        if _overflows(input_path, input_item, self.max_bytes) or _overflows(
            output_path, output_item, self.max_bytes
        ):
            pair += 1
            input_path = self._item_path(INPUT_DIR, pair)
            output_path = self._item_path(OUTPUT_DIR, pair)
        _append(input_path, input_item)
        _append(output_path, output_item)
        self._write_state({"run": run, "pair": pair})

    def _item_path(self, section: str, pair: int) -> Path:
        return self.directory / section / f"{pair:04d}.log"

    def _current_pair(self, state: dict) -> int:
        pair = int(state.get("pair", 1))
        for section in (INPUT_DIR, OUTPUT_DIR):
            section_dir = self.directory / section
            if not section_dir.is_dir():
                continue
            for entry in section_dir.iterdir():
                match = FILE_PATTERN.match(entry.name)
                if match:
                    pair = max(pair, int(match.group(1)))
        return pair

    def _read_state(self) -> dict:
        path = self.directory / STATE_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, state: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / STATE_FILE
        path.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
