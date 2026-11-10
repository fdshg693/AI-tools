"""Discover AGENTS.md files and write (or check) generated rule files."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .targets import Target, output_name, render

IGNORED_DIR_NAMES = {".git", "node_modules", ".venv", "__pycache__"}
CONFIG_FILE_NAME = "ai-tools.yaml"


class GenerateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Planned:
    source: Path
    target_path: Path
    content: str

    @property
    def status(self) -> str:
        if not self.target_path.is_file():
            return "new"
        current = self.target_path.read_text(encoding="utf-8")
        return "unchanged" if current == self.content else "changed"


def find_repo_root(start: Path) -> Path:
    """Walk up from ``start`` to the nearest dir with ``.git`` (then ``ai-tools.yaml``)."""

    start = start.resolve()
    candidates = [start, *start.parents]
    for marker in (".git", CONFIG_FILE_NAME):
        for directory in candidates:
            if (directory / marker).exists():
                return directory
    raise GenerateError(
        f"{start} から親を辿っても .git / {CONFIG_FILE_NAME} が見つかりません。"
        "--repo-root でリポジトリルートを指定してください。"
    )


def discover_agents(repo_root: Path, excludes: list[str]) -> list[Path]:
    """Return repository AGENTS.md files in deterministic order."""

    agents: list[Path] = []
    for current_dir, dir_names, file_names in os.walk(repo_root):
        rel_dir = Path(current_dir).relative_to(repo_root).as_posix()
        dir_names[:] = sorted(
            name
            for name in dir_names
            if name not in IGNORED_DIR_NAMES
            and not _excluded(f"{name}" if rel_dir == "." else f"{rel_dir}/{name}", excludes)
        )
        if "AGENTS.md" in file_names:
            agents.append(Path(current_dir) / "AGENTS.md")
    return sorted(agents, key=lambda path: path.relative_to(repo_root).as_posix())


def _excluded(rel_path: str, excludes: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in excludes)


def configured_output_dir(repo_root: Path, target: Target) -> str:
    """Return ``output_dir`` from ai-tools.yaml when present, else the target default."""

    config_path = repo_root / CONFIG_FILE_NAME
    if not config_path.is_file():
        return target.default_output_dir
    data: Any = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    tool_key, section_key = target.config_key
    section = (data.get("tools") or {}).get(tool_key, {}).get(section_key) or {}
    return section.get("output_dir") or target.default_output_dir


def plan(repo_root: Path, output_dir: Path, target: Target, agents: list[Path]) -> list[Planned]:
    planned: list[Planned] = []
    for agent_path in agents:
        directory = agent_path.parent.relative_to(repo_root)
        planned.append(
            Planned(
                source=agent_path,
                target_path=output_dir / output_name(directory, target),
                content=render(agent_path, directory, target),
            )
        )
    return planned


def write(item: Planned) -> None:
    item.target_path.parent.mkdir(parents=True, exist_ok=True)
    item.target_path.write_text(item.content, encoding="utf-8", newline="\n")
