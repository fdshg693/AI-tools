from __future__ import annotations

import json
from collections.abc import Mapping, Sequence


def status_for(loaded: Sequence[tuple[str, Mapping[str, object]]], key: str) -> str:
    present = [values[key] for _, values in loaded if key in values]
    if len(present) < len(loaded):
        if _values_differ(present):
            return "different"
        return "missing"
    if _values_differ(present):
        return "different"
    return "same"


def values_json(loaded: Sequence[tuple[str, Mapping[str, object]]], key: str) -> str:
    parts: list[str] = []
    for name, values in loaded:
        encoded_name = json.dumps(name, ensure_ascii=False)
        if key not in values:
            parts.append(f"{encoded_name}: null")
        else:
            encoded = json.dumps(values[key], ensure_ascii=False, sort_keys=True)
            parts.append(f"{encoded_name}: {encoded}")
    return "{" + ", ".join(parts) + "}"


def _values_differ(values: list[object]) -> bool:
    return any(value != values[0] for value in values[1:])
