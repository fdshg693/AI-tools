r"""Measure real Tavily research completion times to pick sane research timeouts.

``research_topic.py`` waits a fixed ``max_wait_seconds`` per detail preset
(quick=120s, balanced=180s, max=300s) and reports INCOMPLETE if the run has not
reached a terminal status by then. The audit log shows real Zenn-style questions
blowing past 180s on ``auto``, so those presets are likely too short. This script
gathers the data to choose better numbers.

Approach: launch several research jobs CONCURRENTLY (each runs server-side, so
the wall-clock is ~= the slowest single job, not the sum), then poll all of them
until each reaches a terminal status or a generous global cap. Per-job results
are written INCREMENTALLY to ``measure_research_timing_result.json`` after every
poll, so a long background run can be observed live and partial data survives an
early kill.

Run (PowerShell), ideally in the background so it can run for many minutes:
    python .\tools\tav-cli\experiments\measure_research_timing.py

Optional flags:
    --cap-seconds 1200     global wait cap (default 1200 = 20 min)
    --poll-seconds 10      poll interval (default 10)
    --only mini,auto       restrict to jobs whose model is in this list
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from tav_core import create_tavily_client  # noqa: E402

TERMINAL = {"completed", "failed", "cancelled"}
RESULT_PATH = Path(__file__).resolve().parent / "measure_research_timing_result.json"

# Question complexity tiers. "complex" mirrors the real Zenn data-platform
# question that timed out at 180s in the audit log.
QUESTIONS: dict[str, str] = {
    "simple": "In one short paragraph, what is the Python GIL?",
    "medium": (
        "Explain for a beginner the differences between data lakes, data "
        "warehouses, and lakehouses, and when each is used."
    ),
    "complex": (
        "データエンジニアとはどんな職種で、どんな需要があるか。ETL/ELT、データレイク・"
        "データウェアハウス・レイクハウス、バッチとストリーミング、メダリオンアーキテクチャ、"
        "データガバナンスといったデータ基盤の基本概念を、初学者向けに整理してください。"
        "公式ドキュメント(Microsoft Learn, Databricks, AWS等)や信頼できる解説を優先し、"
        "Microsoft Fabricのような統合データプラットフォームを理解する前段として重要な概念を"
        "洗い出してください。"
    ),
}

# (label, model, question_tier). Models map to the presets that actually time
# out (balanced=auto, max=pro); mini is the cheap quick floor.
MATRIX: list[tuple[str, str, str]] = [
    ("simple/mini", "mini", "simple"),
    ("simple/auto", "auto", "simple"),
    ("medium/auto", "auto", "medium"),
    ("medium/pro", "pro", "medium"),
    ("complex/auto", "auto", "complex"),
    ("complex/pro", "pro", "complex"),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--cap-seconds", type=float, default=1200.0)
    p.add_argument("--poll-seconds", type=float, default=10.0)
    p.add_argument("--only", default="", help="comma-separated model allow-list (mini,auto,pro)")
    return p.parse_args()


def write_results(jobs: list[dict[str, Any]], *, started_wall: str, cap: float, done: bool) -> None:
    payload = {
        "started_at": started_wall,
        "cap_seconds": cap,
        "finished": done,
        "jobs": jobs,
    }
    RESULT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    allow = {m.strip() for m in args.only.split(",") if m.strip()}
    client, _ = create_tavily_client()

    started_wall = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    t0 = time.monotonic()

    jobs: list[dict[str, Any]] = []
    for label, model, tier in MATRIX:
        if allow and model not in allow:
            continue
        job: dict[str, Any] = {
            "label": label,
            "model": model,
            "tier": tier,
            "request_id": None,
            "status": "launching",
            "elapsed_seconds": None,
            "launch_error": None,
        }
        try:
            initial = client.research(
                input=QUESTIONS[tier],
                model=model,
                citation_format="numbered",
                timeout=60.0,
            )
            job["request_id"] = initial.get("request_id")
            job["status"] = initial.get("status")
            job["launched_at_offset"] = round(time.monotonic() - t0, 1)
        except Exception as exc:  # noqa: BLE001 — record, keep launching others
            job["status"] = "launch_failed"
            job["launch_error"] = f"{type(exc).__name__}: {exc}"
        jobs.append(job)
        print(f"launched {label:14} model={model:5} id={job['request_id']} status={job['status']}")

    write_results(jobs, started_wall=started_wall, cap=args.cap_seconds, done=False)

    pending = [j for j in jobs if j["request_id"] and j["status"] not in TERMINAL]
    while pending and (time.monotonic() - t0) < args.cap_seconds:
        time.sleep(args.poll_seconds)
        now = time.monotonic()
        still: list[dict[str, Any]] = []
        for job in pending:
            try:
                resp = client.get_research(job["request_id"])
            except Exception as exc:  # noqa: BLE001
                job["poll_error"] = f"{type(exc).__name__}: {exc}"
                still.append(job)
                continue
            status = resp.get("status")
            job["status"] = status
            if status in TERMINAL:
                job["elapsed_seconds"] = round(now - t0, 1)
                content = resp.get("content")
                job["content_chars"] = len(content) if isinstance(content, str) else None
                job["source_count"] = len(resp.get("sources") or [])
                print(f"  DONE {job['label']:14} status={status} elapsed={job['elapsed_seconds']}s")
            else:
                still.append(job)
        pending = still
        write_results(jobs, started_wall=started_wall, cap=args.cap_seconds, done=not pending)
        elapsed = round(now - t0)
        waiting = ",".join(j["label"] for j in pending)
        print(f"  [{elapsed:5}s] waiting on {len(pending)}: {waiting}")

    # Mark any still-pending jobs as capped.
    for job in pending:
        job["status"] = f"capped({job['status']})"
        job["elapsed_seconds"] = None
    write_results(jobs, started_wall=started_wall, cap=args.cap_seconds, done=True)

    print("\n=== summary ===")
    for job in jobs:
        print(
            f"  {job['label']:14} model={job['model']:5} status={str(job['status']):20} elapsed={job['elapsed_seconds']}"
        )
    print(f"\nWrote {RESULT_PATH}")


if __name__ == "__main__":
    main()
