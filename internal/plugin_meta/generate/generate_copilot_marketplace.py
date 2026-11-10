"""Regenerate copilot-plugins/meta/plugin.json and .github/plugin/marketplace.json
from the skill folders under copilot-plugins/meta.

The skills list is discovered from folder names (any immediate subdirectory of
copilot-plugins/meta containing a SKILL.md). Everything else that can't be
derived from folder names (description, URLs, keywords, version) comes from
ai-tools.yaml; both output files are fully regenerated (not merged) on each
run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from plugin_meta.util.ai_tools_config import REPO_ROOT, load_tool

TOOL_KEY = "copilot"


def find_plugin_dir(tool: dict) -> Path:
    plugin_entries = [plugin for plugin in tool["plugins"] if plugin["kind"] == "plugin"]
    if len(plugin_entries) != 1:
        raise ValueError(
            f"expected exactly one kind=plugin entry for '{TOOL_KEY}' in ai-tools.yaml, "
            f"found {len(plugin_entries)}"
        )
    return REPO_ROOT / plugin_entries[0]["path"]


def discover_skills(plugin_dir: Path) -> list[str]:
    return sorted(
        entry.name
        for entry in plugin_dir.iterdir()
        if entry.is_dir() and (entry / "SKILL.md").is_file()
    )


def build_plugin_manifest(skills: list[str], plugin_config: dict) -> dict:
    return {
        "name": plugin_config["name"],
        "description": plugin_config["description"],
        "version": plugin_config["version"],
        "author": plugin_config["author"],
        "homepage": plugin_config["homepage"],
        "repository": plugin_config["repository"],
        "keywords": plugin_config["keywords"],
        "skills": skills,
    }


def build_marketplace(plugin_manifest: dict, marketplace_config: dict, source: str) -> dict:
    return {
        "name": marketplace_config["name"],
        "owner": plugin_manifest["author"],
        "metadata": marketplace_config["metadata"],
        "plugins": [
            {
                "name": plugin_manifest["name"],
                "description": plugin_manifest["description"],
                "version": plugin_manifest["version"],
                "source": source,
                "repository": plugin_manifest["repository"],
            }
        ],
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    tool = load_tool(TOOL_KEY)
    marketplace_config = tool["marketplace"]
    plugin_dir = find_plugin_dir(tool)
    plugin_json_path = REPO_ROOT / marketplace_config["plugin_json_output_path"]
    marketplace_path = REPO_ROOT / marketplace_config["output_path"]

    skills = discover_skills(plugin_dir)
    if not skills:
        sys.exit(f"error: no SKILL.md found under {plugin_dir}")

    plugin_manifest = build_plugin_manifest(skills, marketplace_config["plugin"])
    write_json(plugin_json_path, plugin_manifest)
    print(f"Wrote {len(skills)} skills to {plugin_json_path}")

    source = f"./{plugin_dir.relative_to(REPO_ROOT).as_posix()}"
    marketplace = build_marketplace(plugin_manifest, marketplace_config, source)
    write_json(marketplace_path, marketplace)
    print(f"Wrote {len(marketplace['plugins'])} plugins to {marketplace_path}")


if __name__ == "__main__":
    main()
