r"""End-to-end check of the foreground->background research handoff (cheap+fast).

We can't wait 5 minutes to watch a real timeout, so we shrink the ``quick`` preset's
foreground wait to a few seconds and ask a trivial question (which really completes
in ~17s). That forces the exact production path: the foreground wait expires, main()
returns INCOMPLETE with NO report file, finalize() spawns the detached poller, and
the poller writes the NNNN-<slug>.md into research/ once the job completes a moment
later. We assert each step.

Run (PowerShell), from the repo root:
    python .\tools\tav-cli\experiments\verify_background_handoff.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

import research_topic  # noqa: E402
from tav_core import ExitCode, finalize  # noqa: E402

TOPIC = "_bg_handoff_test"


def main() -> int:
    out_dir = Path(tempfile.mkdtemp(prefix="tav_bg_test_"))
    os.environ["TAVILY_OUTPUT_DIR"] = str(out_dir)
    os.environ["TAVILY_SHOW_LOG_PATH"] = "false"

    # Force a foreground timeout on a question that really finishes in ~17s, so the
    # detached poller (still using the real background window) takes over and lands.
    # A 1s wait with 1s polling: the API can now finish a trivial question before a
    # 5s first poll, so anything longer may complete in the foreground and skip the handoff.
    research_topic.DETAIL_PRESETS["quick"]["foreground_wait_seconds"] = 1.0
    research_topic.DETAIL_PRESETS["quick"]["poll_interval_seconds"] = 1.0
    research_topic.DETAIL_PRESETS["quick"]["background_wait_seconds"] = 300.0
    research_topic.DETAIL_PRESETS["quick"]["background_poll_interval_seconds"] = 8.0

    research_dir = out_dir / TOPIC / "research"

    print(f"output dir: {out_dir}")
    print("running research with a 1s foreground wait (expect INCOMPLETE + handoff)...")
    outcome = research_topic.main(
        ["In one short paragraph, what is the Python GIL?", "--detail", "quick", "--topic", TOPIC]
    )

    assert outcome.exit_code is ExitCode.INCOMPLETE, (
        f"expected INCOMPLETE, got {outcome.exit_code!r}"
    )
    assert outcome.background is not None, "expected a BackgroundTask to be attached"
    print(f"  foreground exit_code = {outcome.exit_code.name} (correct)")
    print(f"  background argv      = {outcome.background.argv[1:4]} ...")

    # finalize() writes the audit log, writes NO research file, and spawns the poller.
    finalize(outcome)
    no_file_yet = not research_dir.exists() or not list(research_dir.glob("*.md"))
    assert no_file_yet, "foreground must NOT write a report file"
    print("  no report file written by foreground (correct)")

    print("waiting for the detached poller to write the report...")
    deadline = time.monotonic() + 120.0
    md_files: list[Path] = []
    while time.monotonic() < deadline:
        if research_dir.exists():
            md_files = list(research_dir.glob("*.md"))
            if md_files:
                break
        time.sleep(4.0)

    if not md_files:
        print("FAIL: detached poller did not write a report within 120s")
        return 1

    report = md_files[0]
    chars = len(report.read_text(encoding="utf-8"))
    print(f"PASS: background poller wrote {report.name} ({chars} chars)")
    print(f"(temp dir left for inspection: {out_dir})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
