"""Detect SKILL.md files whose content changed vs HEAD without a meta.version bump.

Shared by check_skill_version_bump.py (fails the commit) and
bump_skill_versions.py (auto-bumps the files this reports), so both agree on
exactly which files need a bump.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]

_VERSION_LINE_RE = re.compile(r"^[ \t]*version:\s*.*$")


def staged_skill_md_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--cached", "--diff-filter=ACMR"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip().endswith("SKILL.md")]


def _git_show(rev: str, rel_posix_path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{rev}:{rel_posix_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _frontmatter_span(text: str) -> tuple[int, int] | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return 3, end


def _extract_version(text: str) -> str | None:
    span = _frontmatter_span(text)
    if span is None:
        return None
    start, end = span
    try:
        data = yaml.safe_load(text[start:end])
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return None
    version = meta.get("version")
    if version is None:
        return None
    value = str(version).strip()
    return value or None


def _strip_frontmatter_version(text: str) -> str | None:
    span = _frontmatter_span(text)
    if span is None:
        return None
    start, end = span
    header_lines = [
        line for line in text[start:end].split("\n") if not _VERSION_LINE_RE.match(line)
    ]
    return text[:start] + "\n".join(header_lines) + text[end:]


def find_unbumped_skill_md(paths: list[str] | None) -> list[str]:
    """Return repo-relative posix paths of SKILL.md files needing a version bump.

    ``paths`` defaults to the currently staged SKILL.md files. New files (no
    HEAD revision) and files whose content is unchanged besides the version
    line itself are not reported.
    """
    candidates = paths if paths else staged_skill_md_files()
    failures: list[str] = []

    for raw_path in candidates:
        abs_path = Path(raw_path)
        if not abs_path.is_absolute():
            abs_path = REPO_ROOT / abs_path
        if not abs_path.exists() or abs_path.name != "SKILL.md":
            continue

        rel_posix = abs_path.relative_to(REPO_ROOT).as_posix()
        head_text = _git_show("HEAD", rel_posix)
        if head_text is None:
            continue  # new file: no baseline to bump against

        current_text = abs_path.read_text(encoding="utf-8")

        head_version = _extract_version(head_text)
        current_version = _extract_version(current_text)
        if head_version != current_version:
            continue  # version was bumped, or declared for the first time

        head_stripped = _strip_frontmatter_version(head_text)
        current_stripped = _strip_frontmatter_version(current_text)
        if head_stripped is None or current_stripped is None:
            continue  # unparsable frontmatter; not this check's job
        if head_stripped == current_stripped:
            continue  # nothing changed besides (at most) the version line itself

        failures.append(rel_posix)

    return failures
