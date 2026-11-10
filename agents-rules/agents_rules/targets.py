"""Per-tool rule formats derived from AGENTS.md files.

Each target turns one AGENTS.md into one rule file whose frontmatter scopes
it to the directory containing the source AGENTS.md. The repository-root
AGENTS.md is written as ``root`` and applies to every file.

Antigravity frontmatter key names (trigger/glob/description) are not
documented by Antigravity's official docs (only the trigger *kinds* are);
see _agents/plugins/antigravity-meta/skills/antigravity-memory/SKILL.md.
They were confirmed by inspecting a Rule created through the Antigravity IDE.

Cursor project rules must use the .mdc extension (a plain .md file under
.cursor/rules is ignored by Cursor because it has no rule frontmatter).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Target:
    """One rule format: where it lives and how its frontmatter looks."""

    name: str
    label: str
    default_output_dir: str
    # (ai-tools.yaml tool key, section key) holding `output_dir`, if any.
    config_key: tuple[str, str]
    suffix: str
    render_frontmatter: Callable[[Path], str]


def path_pattern(directory: Path) -> str:
    """Build the glob for files governed by an AGENTS.md in ``directory``."""

    return "**" if directory == Path() else f"{directory.as_posix()}/**"


def _cline(directory: Path) -> str:
    pattern = json.dumps(path_pattern(directory), ensure_ascii=False)
    return f"paths:\n  - {pattern}"


def _copilot(directory: Path) -> str:
    if directory == Path():
        name, scope = "Repository instructions", "the repository"
    else:
        name, scope = f"{directory.as_posix()} instructions", f"{directory.as_posix()}/"
    return (
        f"name: {json.dumps(name, ensure_ascii=False)}\n"
        f"description: {json.dumps(f'Instructions for files in {scope}', ensure_ascii=False)}\n"
        f"applyTo: {json.dumps(path_pattern(directory), ensure_ascii=False)}"
    )


def _antigravity(directory: Path) -> str:
    if directory == Path():
        return "trigger: always_on\nglob:\ndescription:"
    return f"trigger: glob\nglob: {path_pattern(directory)}\ndescription:"


def _cursor(directory: Path) -> str:
    globs = json.dumps(path_pattern(directory), ensure_ascii=False)
    return f"globs: {globs}\nalwaysApply: false"


TARGETS: dict[str, Target] = {
    "cline": Target(
        name="cline",
        label="Cline rules",
        default_output_dir=".clinerules",
        config_key=("cline", "rules_from_agents_md"),
        suffix=".md",
        render_frontmatter=_cline,
    ),
    "copilot": Target(
        name="copilot",
        label="GitHub Copilot instructions",
        default_output_dir=".github/instructions",
        config_key=("copilot", "instructions_from_agents_md"),
        suffix=".instructions.md",
        render_frontmatter=_copilot,
    ),
    "antigravity": Target(
        name="antigravity",
        label="Antigravity rules",
        default_output_dir=".agents/rules",
        config_key=("antigravity", "rules_from_agents_md"),
        suffix=".md",
        render_frontmatter=_antigravity,
    ),
    "cursor": Target(
        name="cursor",
        label="Cursor rules",
        default_output_dir=".cursor/rules",
        config_key=("cursor", "rules_from_agents_md"),
        suffix=".mdc",
        render_frontmatter=_cursor,
    ),
}

# `--target all` expands to these. Cursor reads nested AGENTS.md natively, so
# generating .mdc copies only duplicates content (see .cursor/rules/README.md);
# it stays opt-in via `--target cursor`.
ALL_TARGETS: tuple[str, ...] = ("cline", "copilot", "antigravity")


def output_name(directory: Path, target: Target) -> str:
    """Return the generated file name for an AGENTS.md in ``directory``."""

    stem = "root" if directory == Path() else "-".join(directory.parts)
    return f"{stem}{target.suffix}"


def render(agent_path: Path, directory: Path, target: Target) -> str:
    """Render one rule file while preserving the AGENTS.md body."""

    body = agent_path.read_text(encoding="utf-8").rstrip("\n")
    return f"---\n{target.render_frontmatter(directory)}\n---\n\n{body}\n"
