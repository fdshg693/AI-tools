"""Shared helpers for locating SKILL.md files and reading their YAML frontmatter.

Frontmatter is parsed with yaml.safe_load for reading, but the raw text block is
kept around so callers that need to *patch* a field (e.g. add a missing one) can
do a minimal text edit instead of a full yaml.dump — SKILL.md frontmatter in this
repo often contains hand-written comments that a round-trip dump would destroy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from links.fs import walk_no_links

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    ".astro",
    "generated",
}


@dataclass
class SkillFrontmatter:
    path: Path
    text: str
    raw: str
    raw_end: int
    data: dict[str, Any]

    def with_raw(self, new_raw: str) -> str:
        """Return the full file text with the frontmatter block replaced by new_raw."""
        return self.text[:3] + new_raw + self.text[self.raw_end :]


def find_skill_md_files(root: Path) -> list[Path]:
    # Prune excluded directories during the walk: rglob() would descend into
    # node_modules/.venv first and filter afterwards, which costs seconds per call.
    # Junctions are pruned too (os.walk follows them), so a skill reachable through
    # a junction is never counted or rewritten twice.
    found = []
    for dir_path, _dir_names, file_names in walk_no_links(root, EXCLUDED_DIRECTORY_NAMES):
        if "SKILL.md" in file_names:
            found.append(Path(dir_path) / "SKILL.md")
    return sorted(found)


def read_frontmatter(skill_md_path: Path) -> SkillFrontmatter | None:
    text = skill_md_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    raw = text[3:end]
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return SkillFrontmatter(path=skill_md_path, text=text, raw=raw, raw_end=end, data=data)
