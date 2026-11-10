"""Shared data types and errors for the skill-tools library."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


class SkillToolsError(Exception):
    """Base error that is safe to display to a CLI user."""


class CatalogError(SkillToolsError):
    """The source catalog is malformed or incomplete."""


class SourceError(SkillToolsError):
    """A configured source could not be read safely."""


class ConfigError(SkillToolsError):
    """The skill-tools configuration is invalid."""


class IndexError(SkillToolsError):
    """A CLI index is missing, invalid, or belongs to another source."""


class EmbeddingError(SkillToolsError):
    """An embedding request or response was invalid."""


class InstallError(SkillToolsError):
    """An install could not safely be completed."""


@dataclass(frozen=True)
class SkillBundle:
    """One deployable skill and every source-relative file it contains."""

    canonical_id: str
    name: str
    directory: PurePosixPath
    files: tuple[PurePosixPath, ...]


@dataclass(frozen=True)
class SkillRecord:
    """Catalog metadata and bundle information used by install and search."""

    bundle: SkillBundle
    name: str
    description: str
    body: str
    status: str
    tool: str
    plugin: str

    @property
    def canonical_id(self) -> str:
        return self.bundle.canonical_id

    @property
    def directory(self) -> PurePosixPath:
        return self.bundle.directory

    @property
    def files(self) -> tuple[PurePosixPath, ...]:
        return self.bundle.files


@dataclass(frozen=True)
class HookFile:
    """One file a hook distributes: where it lives in the source and where it is placed."""

    source_path: PurePosixPath
    install_path: PurePosixPath


@dataclass(frozen=True)
class HookAgent:
    """How one hook is delivered to one agent (claude, codex, cursor, antigravity, kilo)."""

    agent: str
    runner: str
    main: PurePosixPath
    files: tuple[HookFile, ...]
    seed_files: tuple[HookFile, ...]
    dependencies: tuple[str, ...]
    registrations: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class HookRecord:
    """One hook from the generated hook catalog, with every agent it supports."""

    id: str
    description: str
    distributable: bool
    requires_tools: tuple[str, ...]
    agents: tuple[HookAgent, ...]

    def agent(self, name: str) -> HookAgent | None:
        return next((item for item in self.agents if item.agent == name), None)

    @property
    def files(self) -> tuple[PurePosixPath, ...]:
        """Every source-relative file this hook references, across all agents."""

        return tuple(
            dict.fromkeys(
                item.source_path
                for agent in self.agents
                for item in (*agent.files, *agent.seed_files)
            )
        )


@dataclass(frozen=True)
class SearchResult:
    """A ranked search result from a CLI index snapshot."""

    path: str
    canonical_id: str
    name: str
    description: str
    tool: str
    plugin: str
    status: str
    score: float
    snippet: str | None


def record_to_index_row(
    record: SkillRecord,
    embedding: list[float],
    embedding_hash: str,
    lexical_hash: str,
    lexical_text: str,
) -> dict[str, Any]:
    """Serialize a record without coupling the index to catalog objects."""

    return {
        "path": record.canonical_id,
        "name": record.name,
        "description": record.description,
        "lexicalHash": lexical_hash,
        "lexicalText": lexical_text,
        "tool": record.tool,
        "plugin": record.plugin,
        "status": {"key": record.status},
        "files": [path.as_posix() for path in record.files],
        "embedding": embedding,
        "embeddingHash": embedding_hash,
    }
