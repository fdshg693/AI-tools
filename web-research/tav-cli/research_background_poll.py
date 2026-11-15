r"""Detached follow-on poller for a research job whose foreground wait expired.

``research_topic.py`` blocks its caller only for a short *foreground* window so an
interactive caller (often an AI agent) is never stuck waiting on a slow research
job. When that window closes with the job still running server-side,
``research_topic.py`` returns ``INCOMPLETE`` immediately and asks ``finalize()`` to
spawn THIS script fully detached (see ``BackgroundTask`` / ``spawn_detached`` in
``tav_core``). It keeps polling ``get_research`` for a much longer *background*
window and:

- on completion, writes the same ``NNNN-<slug>.md`` report into the topic's
  ``research/`` folder via the shared ``finalize()`` machinery — exactly what a
  successful foreground run would have produced; or
- on a failed/cancelled terminal status, or if even the long background window
  expires, writes NO report file. The outcome is recorded ONLY in the audit log
  (``logs/research_background_poll-log.json``), keeping the contract "research
  output is the report or nothing".

This is NOT a ``tav`` subcommand — it is an internal mechanism, spawned by
``research_topic.py`` and never invoked by hand. Its argv is built in
``research_topic.build_background_task``:

    python research_background_poll.py <request_id> --topic NAME --slug TEXT \
        --input "<question>" --detail balanced --model auto \
        --background-wait 1800 --poll-interval 20
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from tavily.errors import InvalidAPIKeyError

from tav_core import (
    ExitCode,
    ResultKind,
    RunOutcome,
    build_response_payload,
    create_tavily_client,
    finalize,
)
from research_topic import (
    DEFAULT_CITATION_FORMAT,
    resolve_exit_code,
    wait_for_research_completion,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Internal: keep polling a research job after the foreground wait expired.",
    )
    parser.add_argument("request_id", help="The research request_id to resume polling.")
    parser.add_argument(
        "--topic", required=True, help="Topic folder to write the report into on completion."
    )
    parser.add_argument("--slug", default="", help="Slug hint for the NNNN-<slug>.md report name.")
    parser.add_argument(
        "--input", default="", help="Original question, recorded in the audit log only."
    )
    parser.add_argument(
        "--detail", default="", help="Original detail preset, recorded in the audit log only."
    )
    parser.add_argument(
        "--model", default="", help="Original model, recorded in the audit log only."
    )
    parser.add_argument(
        "--background-wait", type=float, required=True, help="Max seconds to keep polling."
    )
    parser.add_argument("--poll-interval", type=float, default=20.0, help="Seconds between polls.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> RunOutcome:
    """Resume polling ``request_id`` to completion and return a ``RunOutcome``.

    Returns ``SUCCESS`` (with the report markdown) if the job completes within the
    background window — ``finalize()`` then writes the ``.md`` into ``research/``;
    ``INCOMPLETE`` if the background window also expires; ``RUNTIME_ERROR`` on a
    failed/cancelled terminal status or any polling error. Only the success path
    writes a report file (see ``write_report``); every other path leaves the audit
    log as the sole record.
    """
    args = parse_args(argv)

    try:
        client, config_files = create_tavily_client()
    except ValueError as exc:
        return RunOutcome(exit_code=ExitCode.MISSING_API_KEY, message=str(exc))

    try:
        final_response, completed, elapsed_seconds = wait_for_research_completion(
            client,
            args.request_id,
            max_wait_seconds=args.background_wait,
            poll_interval_seconds=args.poll_interval,
        )
    except InvalidAPIKeyError as exc:
        return RunOutcome(
            exit_code=ExitCode.INVALID_API_KEY, message=f"Invalid Tavily API key: {exc}"
        )
    except Exception as exc:  # noqa: BLE001 — detached run: never raise, record and exit
        return RunOutcome(
            exit_code=ExitCode.RUNTIME_ERROR, message=f"Background research poll failed: {exc}"
        )

    final_status = final_response.get("status")
    exit_code = resolve_exit_code(completed=completed, final_status=final_status)

    payload = build_response_payload(
        script_name=Path(__file__).name,
        request={
            "request_id": args.request_id,
            "input": args.input,
            "detail": args.detail,
            "model": args.model,
            "citation_format": DEFAULT_CITATION_FORMAT,
            "background_wait_seconds": args.background_wait,
            "poll_interval_seconds": args.poll_interval,
            "resumed_in_background": True,
        },
        response={
            "final": final_response,
            "completed_within_wait": completed,
            "elapsed_seconds": round(elapsed_seconds, 2),
        },
        config_files=config_files,
    )

    return RunOutcome(
        exit_code=exit_code,
        topic=args.topic,
        log=payload,
        result_kind=ResultKind.RESEARCH_REPORT,
        result=final_response.get("content") or final_response,
        slug=args.slug or args.input,
        message=None,
    )


if __name__ == "__main__":
    raise SystemExit(finalize(main()))
