from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

MASK = "***"


def status_for(loaded: Sequence[tuple[str, Mapping[str, object]]], key: str) -> str:
    present = [values[key] for _, values in loaded if key in values]
    if len(present) < len(loaded):
        if _values_differ(present):
            return "different"
        return "missing"
    if _values_differ(present):
        return "different"
    return "same"


def values_json(
    loaded: Sequence[tuple[str, Mapping[str, object]]], key: str, *, mask: bool = False
) -> str:
    parts: list[str] = []
    for name, values in loaded:
        encoded_name = json.dumps(name, ensure_ascii=False)
        if key not in values:
            parts.append(f"{encoded_name}: null")
        else:
            value = mask_value(values[key]) if mask else values[key]
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
            parts.append(f"{encoded_name}: {encoded}")
    return "{" + ", ".join(parts) + "}"


def groups_json(loaded: Sequence[tuple[str, Mapping[str, object]]], key: str) -> str:
    """Map each profile to a value-group number (1, 2, ... by first appearance) or null."""
    groups: dict[str, int] = {}
    parts: list[str] = []
    for name, values in loaded:
        encoded_name = json.dumps(name, ensure_ascii=False)
        if key not in values:
            parts.append(f"{encoded_name}: null")
            continue
        canonical = _canonical(values[key])
        number = groups.setdefault(canonical, len(groups) + 1)
        parts.append(f"{encoded_name}: {number}")
    return "{" + ", ".join(parts) + "}"


def mask_value(value: object) -> object:
    """Hide strings but keep the shape: object keys, array lengths, numbers, booleans, null."""
    if isinstance(value, str):
        return MASK
    if isinstance(value, dict):
        return {key: mask_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_value(item) for item in value]
    return value


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _values_differ(values: list[object]) -> bool:
    if not values:
        return False
    first = _canonical(values[0])
    return any(_canonical(value) != first for value in values[1:])
