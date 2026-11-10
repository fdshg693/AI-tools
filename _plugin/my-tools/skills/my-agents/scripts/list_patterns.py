"""List `patterns/*.md` files alongside this skill with their frontmatter `description`.

SKILL.md injects this script's output via a `` ```! `` dynamic-context block so
Claude sees the available usage patterns (and when to use each) immediately on
skill load, without needing to open every file under patterns/ up front.

Usage:
    python list_patterns.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERNS_DIR = Path(__file__).resolve().parent.parent / "patterns"

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.startswith(("#", " ", "\t")):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def main() -> int:
    if not PATTERNS_DIR.is_dir():
        print(f"パターンフォルダが見つかりません: {PATTERNS_DIR}", file=sys.stderr)
        return 1

    paths = sorted(PATTERNS_DIR.glob("*.md"))
    if not paths:
        print("(patterns/ 配下にファイルがありません)")
        return 0

    for path in paths:
        fields = parse_frontmatter(path.read_text(encoding="utf-8"))
        name = fields.get("name", path.stem)
        description = fields.get("description", "(description未設定)")
        print(f"- **{name}** (`patterns/{path.name}`): {description}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
