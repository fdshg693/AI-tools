"""Shared loader for meta_field.yaml, the SSOT for SKILL.md meta: subfield definitions.

Scripts that need field metadata (e.g. enum values for prompt construction)
must read through this module instead of hardcoding values that duplicate
meta_field.yaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
META_FIELD_YAML_PATH = REPO_ROOT / "meta_field.yaml"


def load_meta_fields(path: Path = META_FIELD_YAML_PATH) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"meta_field.yaml not found at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "fields" not in data:
        raise ValueError(f"{path} is missing a top-level 'fields' key")
    return data["fields"]


def get_enum(field: str, path: Path = META_FIELD_YAML_PATH) -> list[str]:
    fields = load_meta_fields(path)
    definition = fields.get(field)
    if not isinstance(definition, dict) or "enum" not in definition:
        raise KeyError(f"meta_field.yaml field '{field}' has no 'enum' entry")
    return list(definition["enum"])
