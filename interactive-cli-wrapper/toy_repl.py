r"""Toy interactive REPL: a fast, deterministic test fixture for exercising
:mod:`icw_core` (spawn / write / read / "back at the prompt" detection).

Not for real use -- the real target is the Cursor CLI's `agent` interactive
mode (Step4), but that process is slow and its output timing is not
deterministic, which makes it a poor CLI to develop and debug the driver
against. This one is spawned directly with ``[sys.executable, "-u",
__file__, ...]`` (an absolute interpreter path, not a shell-resolved
command -- see the Step1 research notes on why bash-wrapper executables like
`agent` needed the same treatment) so tests get full control over startup
delay and how output trickles out.

Each turn: read one line, wait ``--chunk-delay`` seconds ``--chunks-per-turn``
times while printing one echo line per chunk (simulating output that arrives
in bursts rather than all at once), then print the ready prompt again.
"""

from __future__ import annotations

import argparse
import time

READY_PROMPT = "toy> "


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="toy_repl")
    parser.add_argument(
        "--startup-delay",
        type=float,
        default=0.0,
        help="Seconds to sleep before printing the banner and first prompt.",
    )
    parser.add_argument(
        "--chunk-delay",
        type=float,
        default=0.0,
        help="Seconds to sleep before each echoed output line within a turn.",
    )
    parser.add_argument(
        "--chunks-per-turn",
        type=int,
        default=1,
        help="Number of echo lines printed per input line received.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.startup_delay:
        time.sleep(args.startup_delay)
    print("toy interactive CLI (test fixture, not for real use)")
    print(READY_PROMPT, end="", flush=True)

    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() in ("exit", "quit"):
            break
        for i in range(args.chunks_per_turn):
            if args.chunk_delay:
                time.sleep(args.chunk_delay)
            print(f"echo[{i}]: {line}")
        print(READY_PROMPT, end="", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
