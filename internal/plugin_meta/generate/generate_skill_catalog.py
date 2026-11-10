"""Regenerate .claude-plugin/skill-catalog.json from each plugin's skills/ folder.

Walks the claude-code plugins listed in ai-tools.yaml and finds SKILL.md files
located exactly one level under each plugin's "skills" directory
(i.e. skills/<skill-name>/SKILL.md only), then extracts the "name" and
"description" frontmatter fields. The result is grouped by plugin source
path (the "<plugin>" in "<plugin>/skills/<skill-name>/SKILL.md"), each
mapping to its list of skill entries.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from plugin_meta.util.ai_tools_config import REPO_ROOT, load_tool
from skill.util.skill_frontmatter import read_frontmatter

TOOL_KEY = "claude-code"


def load_plugin_source_dirs(tool: dict) -> list[Path]:
    return [REPO_ROOT / plugin["path"] for plugin in tool["plugins"]]


def parse_frontmatter(skill_md_path: Path) -> dict[str, str] | None:
    frontmatter = read_frontmatter(skill_md_path)
    if frontmatter is None:
        return None
    data = frontmatter.data
    if "name" not in data or "description" not in data:
        return None
    return {"name": str(data["name"]), "description": str(data["description"])}


def discover_skills(tool: dict) -> dict[str, list[dict[str, str]]]:
    catalog: dict[str, list[dict[str, str]]] = {}
    for plugin_dir in load_plugin_source_dirs(tool):
        skills_dir = plugin_dir / "skills"
        group_key = plugin_dir.relative_to(REPO_ROOT).as_posix()
        if not skills_dir.is_dir():
            print(f"warning: no skills/ folder under {group_key}", file=sys.stderr)
            continue

        entries = []
        for sub_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
            skill_md_path = sub_dir / "SKILL.md"
            if not skill_md_path.is_file():
                continue
            frontmatter = parse_frontmatter(skill_md_path)
            if frontmatter is None:
                print(
                    f"warning: skipping {skill_md_path.relative_to(REPO_ROOT)} (no name/description frontmatter)",
                    file=sys.stderr,
                )
                continue
            skill_dir = skill_md_path.parent.relative_to(REPO_ROOT)
            entries.append(
                {
                    "path": skill_dir.as_posix(),
                    "name": frontmatter["name"],
                    "description": frontmatter["description"],
                }
            )

        entries.sort(key=lambda entry: entry["path"])
        catalog[group_key] = entries

    return dict(sorted(catalog.items()))


def main() -> None:
    tool = load_tool(TOOL_KEY)
    catalog_path = REPO_ROOT / tool["skill_catalog"]["output_path"]

    catalog = discover_skills(tool)
    output = {
        "_generated_by": "tools/internal/plugin_meta/generate/generate_skill_catalog.py (DO NOT EDIT MANUALLY)",
        **catalog,
    }

    catalog_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    total = sum(len(entries) for entries in catalog.values())
    print(f"Wrote {total} skills across {len(catalog)} groups to {catalog_path}")


if __name__ == "__main__":
    main()
