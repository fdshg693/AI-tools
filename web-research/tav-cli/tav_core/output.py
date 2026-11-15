"""The single output sink: serialization, envelope builders, and ``emit()``.

Every stdout / stderr / file write the package performs goes through ``emit()``,
routed by ``OutputChannel`` (defined in ``result_contract``). Keeping this the
ONLY place output happens is what lets the channel enum actually govern where
bytes go, so a caller can parse stdout verbatim and read stderr as pure
diagnostics. The higher-level "given a ``RunOutcome``, file it under the topic
layout" logic lives in ``topic_layout``; this module is the low-level primitives
it builds on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from tav_core.environment import get_log_dir, get_normalized_api_key, setting_sources
from tav_core.result_contract import (
    ExitCode,
    OutputChannel,
    ResponseEnvelope,
    ResultEnvelope,
    ResultKind,
)


# Audit log directory override (tests set it). ``None`` -> ``environment.get_log_dir()``,
# i.e. ``log_dir`` / ``TAVILY_LOG_DIR``, else ``<output_dir>/.logs``.
LOG_DIRECTORY: Path | None = None


def render_json(payload: Any, *, pretty: bool = True) -> str:
    indent = 2 if pretty else None
    return json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"


def write_output(output_path: Path, payload: Any, *, pretty: bool = True) -> None:
    """Write a file. A ``str`` payload (Markdown) is written verbatim; anything
    else is JSON-serialized. This is what lets ``RESULT_FILE`` carry both the
    ``.json`` discovery/index files and the ``.md`` content/report files without a
    new channel (PLAN.md §2)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else render_json(payload, pretty=pretty)
    output_path.write_text(text, encoding="utf-8")


def build_log_output_path(*, script_name: str) -> Path:
    directory = LOG_DIRECTORY if LOG_DIRECTORY is not None else get_log_dir()
    return directory / f"{Path(script_name).stem}-log.json"


def build_response_payload(
    *,
    script_name: str,
    request: dict[str, Any],
    response: dict[str, Any],
    config_files: list[str],
) -> ResponseEnvelope:
    return {
        "script": script_name,
        "request": request,
        "environment": {
            "config_files": config_files,
            "setting_sources": setting_sources(),
            "api_key_present": bool(get_normalized_api_key()),
        },
        "response": response,
    }


def build_result_envelope(
    *,
    script_name: str,
    result_kind: ResultKind,
    result: Any,
    exit_code: ExitCode,
) -> ResultEnvelope:
    """Assemble the self-describing public envelope emitted to a file or stdout."""
    return {
        "script": script_name,
        "result_kind": result_kind.value,
        "exit_code": int(exit_code),
        "result": result,
    }


def emit(
    channel: OutputChannel, payload: Any, *, path: Path | None = None, pretty: bool = True
) -> None:
    """The single sink for every stdout / stderr / file write in the package.

    Routing is keyed by ``channel`` (see ``OutputChannel``) so the output
    contract lives in one place instead of being scattered across ``print``
    calls. The file channels (``RESULT_FILE`` / ``AUDIT_LOG``) require ``path``;
    the stream channels ignore it. Keeping this the ONLY place output happens is
    what lets ``OutputChannel`` actually govern where bytes go.
    """
    if channel is OutputChannel.DIAGNOSTIC:
        print(payload, file=sys.stderr)
        return
    if channel is OutputChannel.RESULT_STDOUT:
        print(render_json(payload, pretty=pretty), end="")
        return
    if path is None:
        raise ValueError(f"{channel.value} requires a destination path")
    write_output(path, payload, pretty=pretty)
