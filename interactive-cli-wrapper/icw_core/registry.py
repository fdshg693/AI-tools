"""Session metadata: one JSON file per session name.

Persisted under a system temp directory (not the repo) so it survives across
separate CLI invocations -- the whole point of Step3, since an AI agent
driving this wrapper issues one Bash-tool call per action and can't keep a
process handle alive in between (see the Step3 plan's decision table).

Liveness is deliberately NOT read off this file: a crashed/killed daemon
leaves its metadata file behind with no one listening at ``address``.
Callers must attempt an actual IPC connection (:func:`icw_core.ipc.call`)
and treat any failure as "dead" -- this module only stores/retrieves the
data, it never claims a session is alive.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


def sessions_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "icw-sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def metadata_path(name: str) -> Path:
    return sessions_dir() / f"{name}.json"


@dataclass(slots=True)
class SessionMetadata:
    """One session's persisted state.

    ``argv``/``address``/``authkey_hex``/``pid``/``started_at`` and the
    ``initial_*`` fields (the first ``wait_until_ready`` result, captured
    before the daemon starts serving requests) are filled in by
    :mod:`icw_core.daemon` once the child process is spawned. ``error`` is
    the only field set instead of all the above, when the daemon fails
    before ever reaching that point (e.g. the target command doesn't exist)
    -- callers should treat a non-``None`` ``error`` as "never became a live
    session" and discard the metadata rather than trying to connect.
    """

    name: str
    argv: list[str] | None = None
    address: str | None = None
    authkey_hex: str | None = None
    pid: int | None = None
    started_at: str | None = None
    initial_lines: list[str] | None = None
    initial_ready: bool | None = None
    initial_matched_pattern: bool | None = None
    initial_elapsed_seconds: float | None = None
    initial_alive: bool | None = None
    error: str | None = None

    @property
    def authkey(self) -> bytes:
        assert self.authkey_hex is not None, "authkey_hex is unset (daemon never reached ready?)"
        return bytes.fromhex(self.authkey_hex)

    def save(self) -> None:
        metadata_path(self.name).write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, name: str) -> SessionMetadata:
        data = json.loads(metadata_path(name).read_text())
        return cls(**data)


def load_if_exists(name: str) -> SessionMetadata | None:
    """``None`` covers both "no such session" and "unreadable metadata".

    The metadata directory is a shared system temp location that ``list``
    globs in full, so it can contain a file from a session whose daemon is
    mid-write (``SessionMetadata.save`` isn't atomic) or one left corrupt by
    a process that died mid-write in an earlier run. Either way, callers in
    this package already treat "no metadata" as "not alive" -- crashing on a
    transient/corrupt read instead of returning that same ``None`` would
    single-handedly take down ``list`` over one unrelated session.
    """
    path = metadata_path(name)
    if not path.exists():
        return None
    try:
        return SessionMetadata.load(name)
    except (OSError, ValueError, TypeError):
        return None


def delete(name: str) -> None:
    """Best-effort removal: both a CLI caller (``stop``/``send`` noticing a
    dead session) and the daemon itself (cleaning up before it exits, see
    :mod:`icw_core.daemon`) race to delete the same metadata file for the
    same shutdown event. Either side succeeding is enough, so any failure to
    unlink (already gone, or a concurrent unlink mid-flight on Windows) is
    swallowed rather than surfaced.
    """
    try:
        metadata_path(name).unlink()
    except OSError:
        pass


def list_names() -> list[str]:
    return sorted(path.stem for path in sessions_dir().glob("*.json"))
