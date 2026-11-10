"""Local IPC: per-session address resolution + a one-shot request/response call.

Built on ``multiprocessing.connection`` (stdlib) per the Step3 plan's decision
table: a session-persisting daemon (:mod:`icw_core.daemon`) must be reachable
across separate CLI invocations without adding a socket-library dependency,
and ``multiprocessing.connection`` already picks the right transport for the
OS from the address string alone (Windows: named pipe via any ``\\\\``-prefixed
address; POSIX: unix domain socket via any other string address).

Every exchange over this channel is exactly one request dict in, one response
dict out (see :mod:`icw_core.daemon` for the server side of the same
contract) -- there is no persistent session state in the protocol itself,
only in the daemon process holding the actual :class:`icw_core.session.InteractiveSession`.
"""

from __future__ import annotations

import os
import secrets
import tempfile
from multiprocessing.connection import Client
from pathlib import Path


def new_authkey() -> bytes:
    return secrets.token_bytes(32)


def session_address(name: str) -> str:
    """Build the IPC address a session's daemon listens on / clients dial.

    Not derived from :func:`icw_core.registry.sessions_dir` -- the metadata
    file and the IPC address are deliberately separate concerns (metadata
    persists a *name*, this resolves a *transport endpoint* for that name).
    """
    if os.name == "nt":
        return rf"\\.\pipe\icw-{name}"
    socket_dir = Path(tempfile.gettempdir()) / "icw-sessions"
    socket_dir.mkdir(parents=True, exist_ok=True)
    return str(socket_dir / f"icw-{name}.sock")


def call(address: str, authkey: bytes, request: dict, *, timeout: float) -> dict:
    """Connect, send ``request``, wait up to ``timeout`` for one response, disconnect.

    Connecting itself is the liveness check callers rely on (per the Step3
    plan: a session is considered alive only if this actually succeeds, never
    by trusting the metadata file's mere existence) -- any failure to
    connect, or no response within ``timeout``, propagates as an exception
    for the caller to treat as "session not alive".
    """
    conn = Client(address, authkey=authkey)
    try:
        conn.send(request)
        if not conn.poll(timeout):
            raise TimeoutError(f"no response from session within {timeout}s")
        return conn.recv()
    finally:
        conn.close()
