"""The imperative shell: turn a ``RunOutcome`` into side effects.

Architecture: **functional core / imperative shell.** Each wrapper's ``main()``
is a compute step that returns a ``RunOutcome`` value (exit code + payloads +
message) and performs NO output side effects. ``finalize()`` here is the single
shell that turns a ``RunOutcome`` into file writes / prints / detached process
spawns, and a wrapper's ``__main__`` turns the returned code into the process
exit status (``raise SystemExit(finalize(main()))``). This keeps the real product
of ``main()`` in its signature, so it can be tested and composed without
capturing stdout or touching the filesystem.

``finalize()`` delegates the *what-goes-where* of a result to
``topic_layout.emit_payload`` and handles the cross-cutting effects a layout
writer should not own: the single stderr ``message`` and spawning the detached
follow-on process (``spawn_detached``) a long-running op asked for.
"""

from __future__ import annotations

import os
from typing import Any

from tav_core.output import emit
from tav_core.result_contract import (
    BackgroundTask,
    ExitCode,
    OutputChannel,
    RunOutcome,
)
from tav_core.topic_layout import emit_payload


def finalize(outcome: RunOutcome) -> ExitCode:
    """Imperative shell: perform every output side effect a run implies.

    Writes the full log + result envelope (only when there is data to emit),
    prints any stderr ``message``, spawns any detached follow-on, and returns
    ``outcome.exit_code`` so the entry point can do
    ``raise SystemExit(finalize(main()))``. This is the ONLY place wrapper scripts
    touch stdout/stderr/the filesystem/subprocesses for their result.
    """
    if outcome.log is not None and outcome.result_kind is not None:
        emit_payload(
            outcome.log,
            topic=outcome.topic,
            result_kind=outcome.result_kind,
            result=outcome.result,
            exit_code=outcome.exit_code,
            slug=outcome.slug,
            discovery=outcome.discovery,
        )
    if outcome.message:
        emit(OutputChannel.DIAGNOSTIC, outcome.message)
    if outcome.background is not None:
        spawn_detached(outcome.background)
    return outcome.exit_code


def spawn_detached(task: BackgroundTask) -> None:
    """Launch ``task.argv`` as a process that fully outlives this one.

    The child must survive the parent exiting and must not hold the parent's
    console (the parent typically returns control to an interactive caller right
    after). On Windows that means ``DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP``;
    on POSIX a new session (``start_new_session``). The child's std streams are
    detached: it talks to no one — it persists its result to the topic folder and
    its outcome to the audit log. A spawn failure is swallowed to a stderr
    ``DIAGNOSTIC`` so it can never turn a returned ``INCOMPLETE`` into a crash.
    """
    import subprocess

    kwargs: dict[str, Any] = {
        "cwd": task.cwd,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(task.argv, **kwargs)  # noqa: S603 — argv is built internally, not from user shell input
    except OSError as exc:
        emit(OutputChannel.DIAGNOSTIC, f"Could not spawn background poller: {exc}")
