"""Minimal example of calling a local Codex agent through the Python SDK."""

from __future__ import annotations

import argparse
from pathlib import Path

from openai_codex import Codex, Sandbox


MODEL = "gpt-5.6-luna"


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask gpt-5.6-luna one question via Codex SDK")
    parser.add_argument(
        "prompt",
        nargs="?",
        default="1+1=",
        help="Prompt to send to the Codex agent",
    )
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[2]
    with Codex() as codex:
        thread = codex.thread_start(
            model=MODEL,
            cwd=str(repository_root),
            sandbox=Sandbox.read_only,
        )
        result = thread.run(args.prompt)

    print(result.final_response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
