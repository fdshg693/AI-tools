"""Shared loader for repo-tools.yaml, the SSOT for tools/-installed CLI tools
that SKILL.md meta.requires_repo_tools / meta.requires_install declare, and
for tool-to-tool edges (requires_tools).

Scripts that need this mapping (skill_meta_field_fill.py's classification
prompt, check_skill_repo_tools.py, check_repo_tool_relations.py) must read
through this module instead of hardcoding tool names/paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
REPO_TOOLS_YAML_PATH = REPO_ROOT / "repo-tools.yaml"

REQUIRES_TOOLS_KINDS = frozenset({"library", "subprocess", "family"})


class RequiresToolsError(ValueError):
    """requires_tools is present but not a name -> kind mapping."""


def load_repo_tools(path: Path = REPO_TOOLS_YAML_PATH) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"repo-tools.yaml not found at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "tools" not in data:
        raise ValueError(f"{path} is missing a top-level 'tools' key")
    return data["tools"]


def requires_tools_of(entry: dict[str, Any]) -> dict[str, str]:
    """Return tool-name -> kind. Missing or empty means no intra-repo tool deps."""
    if "requires_tools" not in entry or entry["requires_tools"] is None:
        return {}
    raw = entry["requires_tools"]
    if raw == {}:
        return {}
    if not isinstance(raw, dict):
        raise RequiresToolsError("requires_tools must be a mapping of tool name to kind")
    result: dict[str, str] = {}
    for key, kind in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise RequiresToolsError("requires_tools keys must be non-empty tool names")
        if not isinstance(kind, str) or not kind.strip():
            raise RequiresToolsError(
                f"requires_tools[{key!r}] must be a kind "
                f"({' / '.join(sorted(REQUIRES_TOOLS_KINDS))})"
            )
        result[key] = kind
    return result
