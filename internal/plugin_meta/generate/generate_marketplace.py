"""Regenerate .claude-plugin/marketplace.json from the claude-code plugins
listed in ai-tools.yaml.

Top-level marketplace fields (name, owner, metadata) and the plugin list come
from ai-tools.yaml; the file is fully regenerated (not merged) on each run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from plugin_meta.util.ai_tools_config import REPO_ROOT, load_tool

TOOL_KEY = "claude-code"


def manifest_entry(plugin_dir: Path, source: str) -> dict | None:
    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    if not manifest_path.is_file():
        print(
            f"warning: skipping {plugin_dir.relative_to(REPO_ROOT)} (no .claude-plugin/plugin.json)",
            file=sys.stderr,
        )
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "name": manifest["name"],
        "source": source,
        "description": manifest["description"],
        "version": manifest["version"],
        "strict": True,
    }


def discover_plugins(tool: dict) -> list[dict]:
    entries = []
    for plugin in tool["plugins"]:
        plugin_dir = REPO_ROOT / plugin["path"]
        rel_path = plugin_dir.relative_to(REPO_ROOT).as_posix()
        source = "./" if rel_path == "." else f"./{rel_path}"
        entry = manifest_entry(plugin_dir, source)
        if entry is not None:
            entries.append(entry)

    return entries


def main() -> None:
    tool = load_tool(TOOL_KEY)
    marketplace_config = tool["marketplace"]
    marketplace_path = REPO_ROOT / marketplace_config["output_path"]

    marketplace = {
        "name": marketplace_config["name"],
        "owner": marketplace_config["owner"],
        "metadata": marketplace_config["metadata"],
        "plugins": discover_plugins(tool),
    }

    marketplace_path.write_text(
        json.dumps(marketplace, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(marketplace['plugins'])} plugins to {marketplace_path}")


if __name__ == "__main__":
    main()
