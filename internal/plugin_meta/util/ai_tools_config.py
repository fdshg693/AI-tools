"""Shared loader for ai-tools.yaml, the SSOT for AI tool / plugin / marketplace /
skill-catalog locations in this repository.

generate_*.py scripts must read tool configuration through load_tool() instead
of hardcoding paths or metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = REPO_ROOT / "ai-tools.yaml"


def load_config(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not config_path.is_file():
        raise FileNotFoundError(f"ai-tools.yaml not found at {config_path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "tools" not in data:
        raise ValueError(f"{config_path} is missing a top-level 'tools' key")
    return data


def load_tool(tool_key: str, config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    tools = load_config(config_path)["tools"]
    if tool_key not in tools:
        raise KeyError(f"ai-tools.yaml has no entry for tool '{tool_key}' (known: {sorted(tools)})")
    return tools[tool_key]
