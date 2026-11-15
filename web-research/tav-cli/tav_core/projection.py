"""Result projection: shape result items down to their research-relevant keys.

A separate concern from *where* output is filed (``topic_layout``) and *how* a
run is finalized (``run_shell``): this module only decides *which keys survive*
when a result reaches a topic file or stdout. The allow-lists are
``result_contract.PROJECTION_KEYS``; everything not listed there (``raw_content``
== None on search, empty ``images`` on extract, fetch metadata on site pages, …)
is research-irrelevant noise and dropped. The full untouched objects still live
in the audit log — this only shapes the slim public view.
"""

from __future__ import annotations

from typing import Any

from tav_core.result_contract import PROJECTION_KEYS, ResultKind


def slim_result_item(result_kind: ResultKind, item: Any) -> Any:
    """Project one result item down to its research-relevant keys (PLAN.md §4③).

    Drops keys that carry no signal for research triage/reading (per
    ``PROJECTION_KEYS``). Non-dict items (e.g. a research report str) and kinds
    with no projection are returned unchanged.
    """
    keys = PROJECTION_KEYS.get(result_kind)
    if keys is None or not isinstance(item, dict):
        return item
    return {key: item[key] for key in keys if key in item}


def project_result(result_kind: ResultKind, result: Any) -> Any:
    """Apply ``slim_result_item`` across a result (list -> list, else unchanged)."""
    if isinstance(result, list):
        return [slim_result_item(result_kind, item) for item in result]
    return result
