"""Renders collector results (see collectors/__init__.py for the shared shape) as a
plain-text table: one row per tool x window, no external table library -- the
requirement is a simple terminal listing, not a dashboard.
"""

from __future__ import annotations

from datetime import datetime, timezone

_COLUMNS = ("TOOL", "WINDOW", "USED", "RESETS")


def _format_percent(used_percent) -> str:
    return f"{used_percent:.0f}%" if used_percent is not None else "-"


def _format_resets_at(resets_at) -> str:
    if resets_at is None:
        return "-"
    return (
        datetime.fromtimestamp(resets_at, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    )


def render_table(results: list[dict]) -> str:
    rows = [_COLUMNS]
    for result in results:
        windows = result["windows"]
        if not windows:
            rows.append((result["tool"], "-", "-", "-"))
            continue
        for window in windows:
            rows.append(
                (
                    result["tool"],
                    window["name"],
                    _format_percent(window["used_percent"]),
                    _format_resets_at(window["resets_at"]),
                )
            )

    widths = [max(len(row[i]) for row in rows) for i in range(len(_COLUMNS))]
    lines = []
    for i, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[j]) for j, cell in enumerate(row)))
        if i == 0:
            lines.append("  ".join("-" * widths[j] for j in range(len(_COLUMNS))))
    return "\n".join(lines)
