"""Cache paths, completeness marker, and atomic directory replace."""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyinspect_core.pypi import normalize_name

COMPLETE_NAME = ".complete"
INDEX_NAME = "index.md"
TREE_DIRNAME = "tree"
WHEELS_DIRNAME = "wheels"
SNAPSHOT_NAME = "pypi.json"
LOCK_NAME = ".lock"
_LOCK_WAIT_SECONDS = 30.0
_LOCK_POLL_SECONDS = 0.05


@dataclass
class CacheState:
    status: str
    reason: str
    max_bytes: int
    read_wheel: str | None
    import_wheel: str | None
    import_done: bool
    import_ok: bool

    def to_json(self) -> str:
        return (
            json.dumps(
                {
                    "status": self.status,
                    "reason": self.reason,
                    "max_bytes": self.max_bytes,
                    "read_wheel": self.read_wheel,
                    "import_wheel": self.import_wheel,
                    "import_done": self.import_done,
                    "import_ok": self.import_ok,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheState:
        return cls(
            status=str(data.get("status") or ""),
            reason=str(data.get("reason") or ""),
            max_bytes=int(data.get("max_bytes") or 0),
            read_wheel=data.get("read_wheel") or None,
            import_wheel=data.get("import_wheel") or None,
            import_done=bool(data.get("import_done")),
            import_ok=bool(data.get("import_ok")),
        )


def cache_dir(root: Path, name: str, version: str) -> Path:
    return root / normalize_name(name) / version


def staging_dir(final: Path) -> Path:
    return final.with_name(f"{final.name}.tmp-{os.getpid()}")


def is_complete(directory: Path) -> bool:
    marker = directory / COMPLETE_NAME
    index = directory / INDEX_NAME
    if not marker.is_file() or not index.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return False
    return isinstance(payload, dict) and bool(payload.get("status"))


def load_state(directory: Path) -> CacheState | None:
    if not is_complete(directory):
        return None
    try:
        payload = json.loads((directory / COMPLETE_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return CacheState.from_dict(payload)


def write_state(directory: Path, state: CacheState) -> None:
    (directory / COMPLETE_NAME).write_text(state.to_json(), encoding="utf-8")


def remove_incomplete(directory: Path) -> None:
    if directory.exists() and not is_complete(directory):
        shutil.rmtree(directory, ignore_errors=True)


@contextmanager
def exclusive_lock(lock_path: Path) -> Iterator[None]:
    """Cross-process exclusive lock; released if the holder dies."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+b")
    try:
        fh.seek(0, os.SEEK_END)
        if fh.tell() == 0:
            fh.write(b"\0")
            fh.flush()
        deadline = time.monotonic() + _LOCK_WAIT_SECONDS
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out waiting for cache lock at {lock_path}")
                    time.sleep(_LOCK_POLL_SECONDS)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out waiting for cache lock at {lock_path}")
                    time.sleep(_LOCK_POLL_SECONDS)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def atomic_replace(tmp: Path, dest: Path) -> None:
    """Replace ``dest`` with ``tmp``. Windows cannot rename over an existing dir."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        backup = dest.with_name(f"{dest.name}.old-{os.getpid()}")
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        dest.rename(backup)
        shutil.rmtree(backup, ignore_errors=True)
    tmp.rename(dest)
