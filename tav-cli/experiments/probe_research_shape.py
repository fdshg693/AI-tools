r"""Probe the completed Tavily research response shape (one real, cheap call).

research_topic.py returns ``final_response.get("content") or final_response`` as
its RESEARCH_REPORT result, so we want to confirm: on a completed run, is
``content`` a ``str``? And what does ``get_research`` return at top level (status,
sources shape, etc.)? Uses the ``mini`` model + a narrow question to stay cheap.

Run (PowerShell):
    python .\tools\tav-cli\experiments\probe_research_shape.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from tav_core import create_tavily_client  # noqa: E402

TERMINAL = {"completed", "failed", "cancelled"}


def type_name(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, list):
        inner = sorted({type_name(v) for v in value}) or ["<empty>"]
        return f"list[{'|'.join(inner)}]"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def main() -> None:
    client, _ = create_tavily_client()

    initial = client.research(
        input="In one short paragraph, what is the Python GIL?",
        model="mini",
        citation_format="numbered",
        timeout=60.0,
    )
    print("=== research() initial response ===")
    print({k: type_name(v) for k, v in initial.items()})

    request_id = initial["request_id"]
    deadline = time.monotonic() + 180.0
    resp = client.get_research(request_id)
    while resp.get("status") not in TERMINAL and time.monotonic() < deadline:
        print(f"  status={resp.get('status')} ... waiting")
        time.sleep(5.0)
        resp = client.get_research(request_id)

    print("\n=== get_research() final response top-level ===")
    for k in sorted(resp):
        print(f"  {k:16} types={type_name(resp[k])}")

    print(f"\ncontent is str: {isinstance(resp.get('content'), str)}")
    sources = resp.get("sources") or []
    if sources and isinstance(sources[0], dict):
        print("source[0] keys+types:", {k: type_name(v) for k, v in sources[0].items()})

    out = {
        "initial_keys": {k: type_name(v) for k, v in initial.items()},
        "final_keys": {k: type_name(resp[k]) for k in sorted(resp)},
        "content_is_str": isinstance(resp.get("content"), str),
        "source_keys": sorted({k for s in sources if isinstance(s, dict) for k in s}),
    }
    dest = Path(__file__).resolve().parent / "probe_research_result.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {dest}")


if __name__ == "__main__":
    main()
