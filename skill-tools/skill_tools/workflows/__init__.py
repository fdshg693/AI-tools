"""Read and resolve purpose-oriented workflows from repo-workflows.yaml."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml

from ..models import CatalogError, SkillRecord, SourceError
from ..repo_tools.load import RepoTool, load_repo_tools
from ..source import CatalogSource

WORKFLOWS_FILENAME = "repo-workflows.yaml"
_WORKFLOWS_PATH = PurePosixPath(WORKFLOWS_FILENAME)
_FRONTMATTER = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
_WORKFLOW_KEYS = {"id", "title", "purpose", "requires_env", "steps"}
_STEP_KEYS = {"id", "skill", "tool", "optional", "choice", "when", "handoff"}


@dataclass(frozen=True)
class WorkflowStep:
    id: str
    skill: str | None = None
    tool: str | None = None
    optional: bool = False
    choice: str | None = None
    when: str | None = None
    handoff: str | None = None


@dataclass(frozen=True)
class Workflow:
    id: str
    title: str
    purpose: str
    requires_env: tuple[str, ...]
    steps: tuple[WorkflowStep, ...]
    required_skills: tuple[str, ...]
    required_tools: tuple[str, ...]
    required_env: tuple[str, ...]


def _non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, label)


def _string_list(value: Any, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CatalogError(f"{label} must be a list of strings")
    items = tuple(item.strip() for item in value)
    if any(not item for item in items):
        raise CatalogError(f"{label} items must be non-empty strings")
    return tuple(dict.fromkeys(items))


def _metadata(source: CatalogSource, canonical_id: str) -> Mapping[str, Any]:
    try:
        raw = source.read_file(PurePosixPath(canonical_id)).decode("utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        raise CatalogError(f"{canonical_id}: could not read skill metadata: {exc}") from exc
    match = _FRONTMATTER.match(raw)
    if match is None:
        raise CatalogError(f"{canonical_id}: YAML frontmatter is missing or incomplete")
    try:
        data = yaml.safe_load(match.group("body"))
    except yaml.YAMLError as exc:
        raise CatalogError(f"{canonical_id}: invalid YAML frontmatter: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("meta", {}), dict):
        raise CatalogError(f"{canonical_id}: frontmatter metadata must be a mapping")
    return data.get("meta") or {}


def _csv_metadata(meta: Mapping[str, Any], key: str, canonical_id: str) -> tuple[str, ...]:
    value = meta.get(key, "none")
    if value is None or value == "none":
        return ()
    if not isinstance(value, str):
        raise CatalogError(f"{canonical_id}: meta.{key} must be a string")
    return tuple(
        item.strip() for item in value.split(",") if item.strip() and item.strip() != "none"
    )


def _parse_steps(raw_steps: Any, workflow_id: str, skill_ids: set[str], tool_keys: set[str]):
    if not isinstance(raw_steps, list) or not raw_steps:
        raise CatalogError(f"workflow {workflow_id}: steps must be a non-empty list")
    steps: list[WorkflowStep] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_steps):
        label = f"workflows.{workflow_id}.steps[{index}]"
        if not isinstance(raw, dict):
            raise CatalogError(f"{label} must be a mapping")
        unknown = set(raw) - _STEP_KEYS
        if unknown:
            raise CatalogError(f"{label} contains unknown keys: {', '.join(sorted(unknown))}")
        step_id = _non_empty_string(raw.get("id"), f"{label}.id")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", step_id):
            raise CatalogError(f"{label}.id must be a lowercase slug")
        if step_id in seen_ids:
            raise CatalogError(f"workflow {workflow_id}: duplicate step id {step_id!r}")
        seen_ids.add(step_id)
        skill = _optional_string(raw.get("skill"), f"{label}.skill")
        tool = _optional_string(raw.get("tool"), f"{label}.tool")
        if (skill is None) == (tool is None):
            raise CatalogError(f"{label} must reference exactly one skill or tool")
        if skill is not None and skill not in skill_ids:
            raise CatalogError(f"{label} references unknown skill canonical ID {skill!r}")
        if tool is not None and tool not in tool_keys:
            raise CatalogError(f"{label} references unknown tool key {tool!r}")
        optional = raw.get("optional", False)
        if not isinstance(optional, bool):
            raise CatalogError(f"{label}.optional must be a boolean")
        steps.append(
            WorkflowStep(
                id=step_id,
                skill=skill,
                tool=tool,
                optional=optional,
                choice=_optional_string(raw.get("choice"), f"{label}.choice"),
                when=_optional_string(raw.get("when"), f"{label}.when"),
                handoff=_optional_string(raw.get("handoff"), f"{label}.handoff"),
            )
        )
    return tuple(steps)


def list_workflow_ids(source: CatalogSource) -> tuple[str, ...]:
    """Return workflow ids without validating the skill or tool prerequisite graph.

    A source with no ``repo-workflows.yaml`` has no workflows. A file that exists
    but cannot be parsed still raises ``CatalogError``.
    """

    try:
        raw = source.read_file(_WORKFLOWS_PATH)
    except SourceError as exc:
        if "does not exist" in str(exc):
            return ()
        raise
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise CatalogError(f"{WORKFLOWS_FILENAME} is invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise CatalogError(f"{WORKFLOWS_FILENAME} must contain a workflows list")
    raw_workflows = data.get("workflows")
    if raw_workflows is None:
        raise CatalogError(f"{WORKFLOWS_FILENAME}.workflows must be a list")
    if not isinstance(raw_workflows, list):
        raise CatalogError(f"{WORKFLOWS_FILENAME}.workflows must be a list")
    ids: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_workflows):
        label = f"workflows[{index}]"
        if not isinstance(item, dict):
            raise CatalogError(f"{label} must be a mapping")
        workflow_id = item.get("id")
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            raise CatalogError(f"{label}.id must be a non-empty string")
        workflow_id = workflow_id.strip()
        if workflow_id in seen:
            raise CatalogError(f"duplicate workflow id: {workflow_id}")
        seen.add(workflow_id)
        ids.append(workflow_id)
    return tuple(ids)


def load_workflows(
    source: CatalogSource,
    records: Sequence[SkillRecord],
    tools: Sequence[RepoTool] | None = None,
) -> tuple[Workflow, ...]:
    """Load workflow definitions and validate their skill/tool prerequisite graph."""

    try:
        data = yaml.safe_load(source.read_file(_WORKFLOWS_PATH))
    except yaml.YAMLError as exc:
        raise CatalogError(f"{WORKFLOWS_FILENAME} is invalid YAML: {exc}") from exc
    except SourceError as exc:
        raise CatalogError(f"could not read {WORKFLOWS_FILENAME}: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"version", "workflows"}:
        raise CatalogError(f"{WORKFLOWS_FILENAME} must contain only version and workflows")
    if type(data.get("version")) is not int or data.get("version") != 1:
        raise CatalogError(f"{WORKFLOWS_FILENAME}.version must be 1")
    raw_workflows = data.get("workflows")
    if not isinstance(raw_workflows, list) or not raw_workflows:
        raise CatalogError(f"{WORKFLOWS_FILENAME}.workflows must be a non-empty list")

    skill_by_name: dict[str, list[str]] = {}
    skill_metadata: dict[str, Mapping[str, Any]] = {}
    for record in records:
        skill_by_name.setdefault(record.name, []).append(record.canonical_id)
        skill_metadata[record.canonical_id] = _metadata(source, record.canonical_id)
    for ids in skill_by_name.values():
        ids.sort()
    tool_entries = tuple(tools) if tools is not None else load_repo_tools(source)
    tool_by_identity = {tool.key: tool.key for tool in tool_entries}
    tool_by_identity.update({tool.path.as_posix(): tool.key for tool in tool_entries})

    prerequisites: dict[str, tuple[str, ...]] = {}
    skill_tools: dict[str, tuple[str, ...]] = {}
    skill_env: dict[str, tuple[str, ...]] = {}
    for canonical_id, meta in skill_metadata.items():
        resolved: list[str] = []
        for name in _csv_metadata(meta, "requires_skills", canonical_id):
            matches = skill_by_name.get(name, [])
            if not matches:
                # Existing metadata can depend on skills supplied outside this source catalog.
                continue
            if len(matches) > 1:
                raise CatalogError(f"{canonical_id}: ambiguous prerequisite skill {name!r}")
            resolved.append(matches[0])
        prerequisites[canonical_id] = tuple(resolved)
        skill_tools[canonical_id] = tuple(
            dict.fromkeys(
                tool_by_identity[item]
                for item in _csv_metadata(meta, "requires_repo_tools", canonical_id)
                if item in tool_by_identity
            )
        )
        skill_env[canonical_id] = _csv_metadata(meta, "requires_env", canonical_id)

    workflows: list[Workflow] = []
    workflow_ids: set[str] = set()
    for index, raw in enumerate(raw_workflows):
        label = f"workflows[{index}]"
        if not isinstance(raw, dict):
            raise CatalogError(f"{label} must be a mapping")
        unknown = set(raw) - _WORKFLOW_KEYS
        if unknown:
            raise CatalogError(f"{label} contains unknown keys: {', '.join(sorted(unknown))}")
        workflow_id = _non_empty_string(raw.get("id"), f"{label}.id")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", workflow_id):
            raise CatalogError(f"{label}.id must be a lowercase slug")
        if workflow_id in workflow_ids:
            raise CatalogError(f"duplicate workflow id: {workflow_id}")
        workflow_ids.add(workflow_id)
        title = _non_empty_string(raw.get("title"), f"{label}.title")
        purpose = _non_empty_string(raw.get("purpose"), f"{label}.purpose")
        direct_env = _string_list(raw.get("requires_env"), f"{label}.requires_env")
        steps = _parse_steps(
            raw.get("steps"),
            workflow_id,
            set(skill_metadata),
            {tool.key for tool in tool_entries},
        )
        ordered_skills: list[str] = []
        ordered_tools: list[str] = []
        env = list(direct_env)
        state: dict[str, int] = {}

        def add_skill(canonical_id: str) -> None:
            if state.get(canonical_id) == 1:
                raise CatalogError(f"requires_skills cycle detected at {canonical_id}")
            if state.get(canonical_id) == 2:
                return
            state[canonical_id] = 1
            for dependency in prerequisites[canonical_id]:
                add_skill(dependency)
            ordered_skills.append(canonical_id)
            env.extend(skill_env[canonical_id])
            ordered_tools.extend(skill_tools[canonical_id])
            state[canonical_id] = 2

        for step in steps:
            if step.skill is not None:
                add_skill(step.skill)
            if step.tool is not None:
                ordered_tools.append(step.tool)
        workflows.append(
            Workflow(
                id=workflow_id,
                title=title,
                purpose=purpose,
                requires_env=direct_env,
                steps=steps,
                required_skills=tuple(ordered_skills),
                required_tools=tuple(dict.fromkeys(ordered_tools)),
                required_env=tuple(dict.fromkeys(env)),
            )
        )
    return tuple(workflows)


def select_workflow(workflows: Sequence[Workflow], workflow_id: str) -> Workflow:
    for workflow in workflows:
        if workflow.id == workflow_id:
            return workflow
    raise CatalogError(f"workflow not found: {workflow_id}")
