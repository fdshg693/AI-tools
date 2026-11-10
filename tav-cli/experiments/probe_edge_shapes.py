r"""Second-pass probes for the uncertain corners of the result types.

1. ``extract.failed_results[]`` — force a failure with a junk URL and capture the
   item shape (we only need this lightly; errors get discarded downstream).
2. ``extract.results[].title`` — confirm the undocumented ``title`` key is
   reliably present across varied, unrelated URLs (so we can mark it REQUIRED).

Run (PowerShell):
    python .\tools\tav-cli\experiments\probe_edge_shapes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))

from extract_url_content import resolve_extract_options, run_extract_request  # noqa: E402
from tav_core import create_tavily_client  # noqa: E402


def type_name(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def main() -> None:
    client, _ = create_tavily_client()
    out: dict[str, Any] = {}

    # 1. failed_results shape — junk + unreachable URLs.
    opts = resolve_extract_options("quick", has_query=False)
    bad = run_extract_request(
        client,
        urls=[
            "https://this-domain-should-not-exist-zzz123.example/page",
            "https://httpstat.us/404",
        ],
        query=None,
        extract_options=opts,
    )
    failed = bad["response"].get("failed_results") or []
    print("=== failed_results ===")
    print(f"count: {len(failed)}")
    for item in failed:
        if isinstance(item, dict):
            print("  keys+types:", {k: type_name(v) for k, v in item.items()})
            print("  sample:", json.dumps(item, ensure_ascii=False)[:300])
    out["failed_results_keys"] = sorted(
        {k for item in failed if isinstance(item, dict) for k in item}
    )

    # 2. title presence across varied URLs.
    opts2 = resolve_extract_options("quick", has_query=True)
    varied = run_extract_request(
        client,
        urls=[
            "https://en.wikipedia.org/wiki/Python_(programming_language)",
            "https://www.python.org/",
            "https://docs.python.org/3/library/typing.html",
        ],
        query="overview",
        extract_options=opts2,
    )
    results = varied["response"].get("results") or []
    print("\n=== extract results title check ===")
    title_present = 0
    for item in results:
        has = isinstance(item, dict) and "title" in item
        title_present += int(has)
        print(f"  url={item.get('url')!r} title_present={has} title={item.get('title')!r}")
    out["extract_title_present"] = f"{title_present}/{len(results)}"
    out["extract_result_keys_union"] = sorted(
        {k for item in results if isinstance(item, dict) for k in item}
    )

    dest = Path(__file__).resolve().parent / "probe_edge_result.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {dest}")


if __name__ == "__main__":
    main()
