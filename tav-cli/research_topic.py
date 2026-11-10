r"""Run Tavily research with a small, opinionated CLI.

This wrapper keeps model selection and polling behavior inside the file so
callers only need to provide a research prompt, an optional detail preset, and
an optional JSON output path. Adjust the preset values below when you want
different Tavily research behavior.

PowerShell example:
    python .\tools\tav-cli\research_topic.py "Microsoft Fabric の概要を整理してください" --topic fabric_overview

bash example:
    python ./tools/tav-cli/research_topic.py "Microsoft Fabric の概要を整理してください" --topic fabric_overview
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tavily.errors import InvalidAPIKeyError

from tav_core import (
    TOPIC_ARG_HELP,
    BackgroundTask,
    ExitCode,
    ResultKind,
    RunOutcome,
    build_response_payload,
    create_tavily_client,
    finalize,
    slugify,
)


# Detail presets. The wait is split into two windows (measured: any non-trivial
# research run takes ~270-350s — see experiments/measure_research_timing.py):
#
#   foreground_wait_seconds — how long THIS call blocks the caller. Set above the
#     measured typical completion so most runs finish in-call and the caller gets
#     the report directly (the old single 180s/300s waits gave up too early).
#   background_wait_seconds — if the foreground window still expires mid-run, a
#     detached poller (research_background_poll.py) keeps going this long and
#     writes the report into research/ when it finally completes.
#
# Each window has its own poll cadence (the background one is slower — nobody is
# waiting on it). Edit these to retune; foreground >= the band you want delivered
# synchronously, background generous enough to catch the slow tail.
DETAIL_PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "model": "mini",
        "poll_interval_seconds": 5.0,
        "foreground_wait_seconds": 150.0,
        "background_wait_seconds": 900.0,
        "background_poll_interval_seconds": 15.0,
    },
    "balanced": {
        "model": "auto",
        "poll_interval_seconds": 8.0,
        "foreground_wait_seconds": 360.0,
        "background_wait_seconds": 1800.0,
        "background_poll_interval_seconds": 20.0,
    },
    "max": {
        "model": "pro",
        "poll_interval_seconds": 10.0,
        "foreground_wait_seconds": 420.0,
        "background_wait_seconds": 1800.0,
        "background_poll_interval_seconds": 20.0,
    },
}

DEFAULT_DETAIL = "balanced"
DEFAULT_CITATION_FORMAT = "numbered"
REQUEST_TIMEOUT_SECONDS = 60.0
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

# The detached poller spawned when the foreground wait expires (same directory).
BACKGROUND_POLLER = Path(__file__).resolve().parent / "research_background_poll.py"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Tavily research with minimal arguments and wait for completion.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Role: report. With --topic NAME, writes one report to\n"
            "<TAVILY_OUTPUT_DIR>/NAME/research/NNNN-<question>.md ONLY on success.\n"
            "If the foreground wait expires, a detached poller keeps going and writes\n"
            "that .md later when the job completes; a failure writes no file (the audit\n"
            "log is the record). Omit --topic to print one ResultEnvelope to stdout."
        ),
    )
    parser.add_argument(
        "input",
        help="Research prompt or question to investigate.",
    )
    parser.add_argument(
        "--detail",
        choices=sorted(DETAIL_PRESETS),
        default=DEFAULT_DETAIL,
        help="High-level research preset. Model and polling behavior are predefined.",
    )
    parser.add_argument(
        "--topic",
        help=TOPIC_ARG_HELP,
    )
    return parser.parse_args(argv)


def wait_for_research_completion(
    client: Any,
    request_id: str,
    *,
    max_wait_seconds: float,
    poll_interval_seconds: float,
) -> tuple[dict[str, Any], bool, float]:
    """Poll ``get_research`` until a terminal status or ``max_wait_seconds``.

    Returns ``(last_response, completed, elapsed_seconds)`` where ``completed`` is
    ``False`` iff the wait window expired with the job still running. Timing is
    passed in explicitly (not read from a preset) so the same loop serves both the
    short foreground wait and the long detached background wait.
    """
    deadline = time.monotonic() + max_wait_seconds
    last_response = client.get_research(request_id)

    while last_response.get("status") not in TERMINAL_STATUSES:
        if time.monotonic() >= deadline:
            return last_response, False, max_wait_seconds
        time.sleep(poll_interval_seconds)
        last_response = client.get_research(request_id)

    elapsed_seconds = max_wait_seconds - max(deadline - time.monotonic(), 0.0)
    return last_response, True, elapsed_seconds


def build_background_task(
    request_id: str,
    *,
    topic: str,
    input_text: str,
    detail: str,
    preset: dict[str, Any],
) -> BackgroundTask:
    """Describe the detached poller to spawn when the foreground wait expires.

    The argv re-runs this skill's ``research_background_poll.py`` under the same
    interpreter, passing the live ``request_id`` so it resumes polling (it never
    starts a second research job). ``cwd`` is pinned to the current directory so the
    poller resolves ``TAVILY_OUTPUT_DIR`` to the same ``research/`` folder this run
    would have used. ``main()`` only builds this value; ``finalize()`` spawns it.
    """
    argv = [
        sys.executable,
        str(BACKGROUND_POLLER),
        request_id,
        "--topic",
        topic,
        "--slug",
        slugify(input_text),
        "--input",
        input_text,
        "--detail",
        detail,
        "--model",
        preset["model"],
        "--background-wait",
        str(preset["background_wait_seconds"]),
        "--poll-interval",
        str(preset["background_poll_interval_seconds"]),
    ]
    return BackgroundTask(argv=argv, cwd=os.getcwd())


def resolve_exit_code(*, completed: bool, final_status: str | None) -> ExitCode:
    """Map a finished research run to its exit code (see ``ExitCode``).

    ``INCOMPLETE`` (did not reach a terminal state within the wait window) is
    deliberately distinct from ``RUNTIME_ERROR`` (reached a terminal but
    non-``completed`` status, i.e. failed/cancelled).
    """
    if not completed:
        return ExitCode.INCOMPLETE
    if final_status != "completed":
        return ExitCode.RUNTIME_ERROR
    return ExitCode.SUCCESS


def describe_outcome(
    exit_code: ExitCode,
    final_status: str | None,
    *,
    preset: dict[str, Any],
    topic: str | None,
    request_id: str | None,
    spawned_background: bool,
) -> str | None:
    """The stderr line for a finished foreground research run, or ``None``.

    On a foreground timeout the wording differs by whether a background poller was
    spawned: with one, the caller is told the report will still appear under
    ``research/`` when the job completes (so ``INCOMPLETE`` here is "not yet", not
    "lost"); without one (no ``--topic``, so nowhere to file the result), the
    caller is told how to resume via the ``request_id``.
    """
    if exit_code is ExitCode.INCOMPLETE:
        fg = int(preset["foreground_wait_seconds"])
        if spawned_background:
            bg = int(preset["background_wait_seconds"])
            return (
                f"Research did not finish within the {fg}s foreground wait. A detached "
                f"poller is now continuing in the background for up to {bg}s; if it "
                f"completes, the report will be written under {topic}/research/, "
                "otherwise only the audit log will record the failure (no file is "
                "written here)."
            )
        return (
            f"Research did not finish within the {fg}s foreground wait (request_id="
            f"{request_id}). Pass --topic to have a background poller finish it, or "
            "re-run with a longer --detail preset."
        )
    if exit_code is ExitCode.RUNTIME_ERROR:
        return (
            f"Research finished with status: {final_status} (no report written; see the audit log)."
        )
    return None


def main(argv: Sequence[str] | None = None) -> RunOutcome:
    """Run research, wait for completion, and return a ``RunOutcome`` (no I/O;
    ``finalize()`` emits it).

    The success ``result`` is the report content (markdown) when available, else
    the raw final response, carried as ``RESEARCH_REPORT``. Returns ``SUCCESS`` when
    the run completed within the foreground wait; ``INCOMPLETE`` if it did not — in
    which case, when ``--topic`` is set, a detached background poller is attached
    (via ``RunOutcome.background``) to finish the job and write the report later, and
    NO file is written here now; ``RUNTIME_ERROR`` on a failed/cancelled terminal
    status (also no file — the audit log is the record); ``MISSING_API_KEY`` /
    ``INVALID_API_KEY`` on credential problems.
    """
    args = parse_args(argv)
    preset = DETAIL_PRESETS[args.detail]

    try:
        client, config_files = create_tavily_client()
    except ValueError as exc:
        return RunOutcome(exit_code=ExitCode.MISSING_API_KEY, message=str(exc))

    try:
        initial_response = client.research(
            input=args.input,
            model=preset["model"],
            citation_format=DEFAULT_CITATION_FORMAT,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        request_id = initial_response.get("request_id")
        if not request_id:
            raise RuntimeError("Research response did not include request_id.")

        final_response, completed, elapsed_seconds = wait_for_research_completion(
            client,
            request_id,
            max_wait_seconds=preset["foreground_wait_seconds"],
            poll_interval_seconds=preset["poll_interval_seconds"],
        )
    except InvalidAPIKeyError as exc:
        return RunOutcome(
            exit_code=ExitCode.INVALID_API_KEY, message=f"Invalid Tavily API key: {exc}"
        )
    except Exception as exc:
        return RunOutcome(exit_code=ExitCode.RUNTIME_ERROR, message=f"Research failed: {exc}")

    final_status = final_response.get("status")
    exit_code = resolve_exit_code(completed=completed, final_status=final_status)

    # A foreground timeout with a destination to file the eventual report keeps the
    # job alive: hand back INCOMPLETE now and let a detached poller finish it.
    background = None
    if exit_code is ExitCode.INCOMPLETE and args.topic:
        background = build_background_task(
            request_id,
            topic=args.topic,
            input_text=args.input,
            detail=args.detail,
            preset=preset,
        )

    payload = build_response_payload(
        script_name=Path(__file__).name,
        request={
            "input": args.input,
            "detail": args.detail,
            "model": preset["model"],
            "citation_format": DEFAULT_CITATION_FORMAT,
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "poll_interval_seconds": preset["poll_interval_seconds"],
            "foreground_wait_seconds": preset["foreground_wait_seconds"],
            "background_wait_seconds": preset["background_wait_seconds"],
        },
        response={
            "initial": initial_response,
            "final": final_response,
            "completed_within_wait": completed,
            "elapsed_seconds": round(elapsed_seconds, 2),
            "request_id": request_id,
            "background_poll_spawned": background is not None,
        },
        config_files=config_files,
    )

    return RunOutcome(
        exit_code=exit_code,
        topic=args.topic,
        log=payload,
        result_kind=ResultKind.RESEARCH_REPORT,
        result=final_response.get("content") or final_response,
        slug=args.input,
        message=describe_outcome(
            exit_code,
            final_status,
            preset=preset,
            topic=args.topic,
            request_id=request_id,
            spawned_background=background is not None,
        ),
        background=background,
    )


if __name__ == "__main__":
    raise SystemExit(finalize(main()))
