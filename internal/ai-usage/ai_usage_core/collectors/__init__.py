"""Per-tool collectors. Each `collect()` returns `{"tool": <name>, "windows": [...]}`,
where each window is `{"name": str, "used_percent": float | None, "resets_at": int | None}`.
`used_percent`/`resets_at` are `None` when the tool has no data available right now.
"""
