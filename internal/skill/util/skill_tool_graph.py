"""Skill↔tool relation graph built from SKILL.md frontmatter and repo-tools.yaml.

Forward edges stay in their SSOTs (meta.requires_skills / requires_repo_tools
and repo-tools.yaml requires_tools). This module only indexes them so check/
and query/ can walk downstream without parsing twice.

Does not infer tool↔tool edges from skill metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from skill.util.repo_tools_registry import (
    REPO_ROOT,
    load_repo_tools,
    requires_tools_of,
)
from skill.util.skill_frontmatter import find_skill_md_files, read_frontmatter

NONE_TOKEN = "none"
MUST_SEE_KINDS = frozenset({"library", "subprocess"})
LookLabel = Literal["must-see", "check"]
NodeKind = Literal["skill", "tool"]


def split_meta_csv(value: object) -> tuple[str, ...]:
    """Comma-separated meta scalars → tokens. ``none`` / empty / non-str → ()."""
    if not isinstance(value, str):
        return ()
    parts: list[str] = []
    for raw in value.split(","):
        token = raw.strip()
        if not token or token.lower() == NONE_TOKEN:
            continue
        parts.append(token)
    return tuple(parts)


def path_appears_in(text: str, registered_path: str) -> bool:
    """True if ``registered_path`` is a path-bounded substring of ``text``.

    ``tools/aim`` matches ``uv tool install --editable tools/aim`` and
    ``tools/aim/README.md``, but not ``tools/aim-use/...``.
    """
    if not registered_path:
        return False
    pattern = re.compile(rf"(?<![A-Za-z0-9_.-]){re.escape(registered_path)}(?![A-Za-z0-9_-])")
    return pattern.search(text) is not None


@dataclass(frozen=True)
class SkillNode:
    name: str
    rel_posix: str
    requires_skills: tuple[str, ...]
    requires_repo_tools: tuple[str, ...]
    requires_install: tuple[str, ...]


@dataclass(frozen=True)
class ToolNode:
    key: str
    path: str
    install: str
    requires_tools: dict[str, str]


@dataclass(frozen=True)
class ImpactHit:
    kind: NodeKind
    name: str
    path: str
    via: str
    hop: int
    look: LookLabel


@dataclass
class SkillToolGraph:
    skills: list[SkillNode]
    tools: dict[str, ToolNode]
    skills_by_name: dict[str, list[SkillNode]] = field(default_factory=dict)
    tool_by_path: dict[str, ToolNode] = field(default_factory=dict)
    tools_depending_on: dict[str, list[tuple[str, str]]] = field(default_factory=dict)

    def tool_keys_mentioned(self, tokens: tuple[str, ...]) -> set[str]:
        """Resolve requires_repo_tools tokens (key or registered path) to keys."""
        keys: set[str] = set()
        for token in tokens:
            tool = self.tools.get(token) or self.tool_by_path.get(_posix(token))
            if tool is not None:
                keys.add(tool.key)
        return keys

    def install_mentions_tool(self, tokens: tuple[str, ...], tool: ToolNode) -> bool:
        """requires_install item matches key, path, or install command."""
        for token in tokens:
            if token == tool.key or token == tool.path:
                return True
            if tool.install and (token == tool.install or tool.install in token):
                return True
            if path_appears_in(token, tool.path):
                return True
        return False

    def skills_referencing_tool(self, tool_key: str) -> list[tuple[SkillNode, str]]:
        """Skills whose requires_repo_tools or requires_install resolve to ``tool_key``."""
        tool = self.tools.get(tool_key)
        if tool is None:
            return []
        hits: list[tuple[SkillNode, str]] = []
        for skill in self.skills:
            via: list[str] = []
            if tool_key in self.tool_keys_mentioned(skill.requires_repo_tools):
                via.append("requires_repo_tools")
            if self.install_mentions_tool(skill.requires_install, tool):
                via.append("requires_install")
            if via:
                hits.append((skill, "+".join(via)))
        return hits

    def skills_requiring_skill(self, skill_name: str) -> list[SkillNode]:
        if not skill_name:
            return []
        return [skill for skill in self.skills if skill_name in skill.requires_skills]


def _posix(raw: str) -> str:
    return raw.replace("\\", "/").rstrip("/")


def load_graph(
    repo_root: Path | None = None,
    tools: dict | None = None,
    skill_md_paths: list[Path] | None = None,
) -> SkillToolGraph:
    root = repo_root if repo_root is not None else REPO_ROOT
    registry = tools if tools is not None else load_repo_tools()
    tool_nodes: dict[str, ToolNode] = {}
    tool_by_path: dict[str, ToolNode] = {}
    tools_depending_on: dict[str, list[tuple[str, str]]] = {}

    for key, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        path_str = path.strip() if isinstance(path, str) else ""
        install = entry.get("install")
        install_str = install.strip() if isinstance(install, str) else ""
        node = ToolNode(
            key=key,
            path=_posix(path_str),
            install=install_str,
            requires_tools=dict(requires_tools_of(entry)),
        )
        tool_nodes[key] = node
        if node.path:
            tool_by_path[node.path] = node
        for target, kind in node.requires_tools.items():
            tools_depending_on.setdefault(target, []).append((key, kind))

    paths = skill_md_paths if skill_md_paths is not None else find_skill_md_files(root)
    skills: list[SkillNode] = []
    skills_by_name: dict[str, list[SkillNode]] = {}
    for skill_md_path in paths:
        frontmatter = read_frontmatter(skill_md_path)
        if frontmatter is None:
            continue
        data = frontmatter.data
        raw_name = data.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        meta = data.get("meta")
        meta_dict = meta if isinstance(meta, dict) else {}
        node = SkillNode(
            name=name,
            rel_posix=skill_md_path.relative_to(root).as_posix(),
            requires_skills=split_meta_csv(meta_dict.get("requires_skills")),
            requires_repo_tools=split_meta_csv(meta_dict.get("requires_repo_tools")),
            requires_install=split_meta_csv(meta_dict.get("requires_install")),
        )
        skills.append(node)
        if name:
            skills_by_name.setdefault(name, []).append(node)

    return SkillToolGraph(
        skills=skills,
        tools=tool_nodes,
        skills_by_name=skills_by_name,
        tool_by_path=tool_by_path,
        tools_depending_on=tools_depending_on,
    )


def _look_for_tool_kind(kind: str) -> LookLabel:
    return "must-see" if kind in MUST_SEE_KINDS else "check"


def _stronger_look(left: LookLabel, right: LookLabel) -> LookLabel:
    return "must-see" if "must-see" in (left, right) else "check"


@dataclass
class ResolvedTarget:
    kind: NodeKind
    name: str
    path: str
    skill_names: tuple[str, ...] = ()
    tool_key: str | None = None


class UnknownTargetError(ValueError):
    """Input did not match a skill name, tool key, SKILL.md, or registered path."""


def resolve_skill_md_path(raw: str, repo_root: Path) -> Path | None:
    candidate = Path(raw)
    options = (
        [candidate] if candidate.is_absolute() else [repo_root / candidate, Path.cwd() / candidate]
    )
    for option in options:
        try:
            resolved = option.resolve()
        except OSError:
            continue
        if resolved.is_file() and resolved.name == "SKILL.md":
            return resolved
        if resolved.is_dir() and (resolved / "SKILL.md").is_file():
            return resolved / "SKILL.md"
    return None


def resolve_target(raw: str, graph: SkillToolGraph, repo_root: Path) -> ResolvedTarget:
    text = raw.strip()
    if not text:
        raise UnknownTargetError("empty target")

    skill_md = resolve_skill_md_path(text, repo_root)
    if skill_md is not None:
        rel = skill_md.relative_to(repo_root).as_posix()
        for skill in graph.skills:
            if skill.rel_posix == rel:
                return ResolvedTarget(
                    kind="skill",
                    name=skill.name or rel,
                    path=rel,
                    skill_names=(skill.name,) if skill.name else (),
                )
        raise UnknownTargetError(f"{rel} has no readable SKILL.md frontmatter")

    posix = _posix(text)
    tool = graph.tool_by_path.get(posix)
    if tool is not None:
        return ResolvedTarget(kind="tool", name=tool.key, path=tool.path, tool_key=tool.key)

    tool = graph.tools.get(text)
    if tool is not None:
        return ResolvedTarget(kind="tool", name=tool.key, path=tool.path, tool_key=tool.key)

    named = graph.skills_by_name.get(text)
    if named:
        return ResolvedTarget(
            kind="skill",
            name=text,
            path=", ".join(skill.rel_posix for skill in named),
            skill_names=(text,),
        )

    raise UnknownTargetError(
        f"{text!r} is not a skill name, tool key, SKILL.md path, or registered tools/ path"
    )


def _record_hit(
    hits: dict[tuple[str, str], ImpactHit],
    hit: ImpactHit,
) -> None:
    key = (hit.kind, hit.path)
    existing = hits.get(key)
    if existing is None:
        hits[key] = hit
        return
    look = _stronger_look(existing.look, hit.look)
    hop = min(existing.hop, hit.hop)
    via = existing.via if existing.hop < hit.hop else hit.via
    if existing.hop == hit.hop and hit.via not in existing.via.split("; "):
        via = f"{existing.via}; {hit.via}"
    hits[key] = ImpactHit(
        kind=existing.kind,
        name=existing.name,
        path=existing.path,
        via=via,
        hop=hop,
        look=look,
    )


def _walk_skill_consumers(
    graph: SkillToolGraph,
    seeds: dict[str, tuple[int, LookLabel]],
    hits: dict[tuple[str, str], ImpactHit],
) -> None:
    """One reverse requires_skills hop from ``seeds`` (name → hop, look). Seeds are not re-emitted.

    Further skill hops are out of scope: the design path is tool→skill→skill
    (digest). Cycle cuts for tool→tool live in impact_from_tool.
    """
    for name, (hop, look) in seeds.items():
        if not name:
            continue
        consumer_names = {skill.name for skill in graph.skills_requiring_skill(name) if skill.name}
        for consumer_name in sorted(consumer_names):
            for copy in graph.skills_by_name.get(consumer_name, []):
                _record_hit(
                    hits,
                    ImpactHit(
                        kind="skill",
                        name=copy.name,
                        path=copy.rel_posix,
                        via=f"requires_skills:{name}",
                        hop=hop + 1,
                        look=look,
                    ),
                )


def impact_from_skill(graph: SkillToolGraph, skill_names: tuple[str, ...]) -> list[ImpactHit]:
    hits: dict[tuple[str, str], ImpactHit] = {}
    seeds = {name: (0, "must-see") for name in skill_names if name}
    _walk_skill_consumers(graph, seeds, hits)
    return _sorted_hits(hits)


def impact_from_tool(graph: SkillToolGraph, tool_key: str) -> list[ImpactHit]:
    hits: dict[tuple[str, str], ImpactHit] = {}
    visited_tools = {tool_key}
    queue: list[tuple[str, int, LookLabel]] = [(tool_key, 0, "must-see")]

    while queue:
        current, hop, incoming_look = queue.pop(0)
        for skill, via in graph.skills_referencing_tool(current):
            _record_hit(
                hits,
                ImpactHit(
                    kind="skill",
                    name=skill.name or skill.rel_posix,
                    path=skill.rel_posix,
                    via=via if current == tool_key else f"{via} via {current}",
                    hop=hop + 1,
                    look=incoming_look,
                ),
            )
        for consumer_key, kind in graph.tools_depending_on.get(current, []):
            if consumer_key in visited_tools:
                continue
            visited_tools.add(consumer_key)
            consumer = graph.tools.get(consumer_key)
            if consumer is None:
                continue
            look = incoming_look if incoming_look == "check" else _look_for_tool_kind(kind)
            _record_hit(
                hits,
                ImpactHit(
                    kind="tool",
                    name=consumer.key,
                    path=consumer.path,
                    via=f"requires_tools:{kind}",
                    hop=hop + 1,
                    look=look,
                ),
            )
            queue.append((consumer_key, hop + 1, look))

    seeds: dict[str, tuple[int, LookLabel]] = {}
    for hit in hits.values():
        if hit.kind != "skill" or not hit.name:
            continue
        prev = seeds.get(hit.name)
        if prev is None or hit.hop < prev[0]:
            seeds[hit.name] = (hit.hop, hit.look)
        elif hit.hop == prev[0]:
            seeds[hit.name] = (hit.hop, _stronger_look(prev[1], hit.look))
    _walk_skill_consumers(graph, seeds, hits)
    return _sorted_hits(hits)


def impact_for_target(graph: SkillToolGraph, target: ResolvedTarget) -> list[ImpactHit]:
    if target.kind == "tool" and target.tool_key:
        return impact_from_tool(graph, target.tool_key)
    return impact_from_skill(graph, target.skill_names)


def _sorted_hits(hits: dict[tuple[str, str], ImpactHit]) -> list[ImpactHit]:
    order = {"tool": 0, "skill": 1}
    look_order = {"must-see": 0, "check": 1}
    return sorted(
        hits.values(),
        key=lambda hit: (order[hit.kind], hit.hop, look_order[hit.look], hit.path),
    )
