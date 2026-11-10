"""Regenerate .agents/plugins/marketplace.json from the codex plugins listed
in ai-tools.yaml.

Plugin paths in the generated catalog are relative to the repository root, as
required for a repo-scoped Codex marketplace.
"""

from __future__ import annotations

import json
from pathlib import Path

from plugin_meta.util.ai_tools_config import REPO_ROOT, load_tool

TOOL_KEY = "codex"


def manifest_entry(manifest_path: Path, default_category: str) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugin_dir = manifest_path.parent.parent
    relative_plugin_dir = plugin_dir.relative_to(REPO_ROOT).as_posix()
    category = manifest.get("interface", {}).get("category", default_category)

    return {
        "name": manifest["name"],
        "source": {
            "source": "local",
            "path": f"./{relative_plugin_dir}",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": category,
    }


def discover_plugins(tool: dict, default_category: str) -> list[dict]:
    manifest_paths = [
        REPO_ROOT / plugin["path"] / ".codex-plugin" / "plugin.json" for plugin in tool["plugins"]
    ]
    return [manifest_entry(manifest_path, default_category) for manifest_path in manifest_paths]


def main() -> None:
    tool = load_tool(TOOL_KEY)
    marketplace_config = tool["marketplace"]
    marketplace_path = REPO_ROOT / marketplace_config["output_path"]

    marketplace = {
        "name": marketplace_config["name"],
        "interface": marketplace_config["interface"],
        "plugins": discover_plugins(tool, marketplace_config["default_category"]),
    }

    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    marketplace_path.write_text(
        json.dumps(marketplace, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(marketplace['plugins'])} plugins to {marketplace_path}")


if __name__ == "__main__":
    main()
