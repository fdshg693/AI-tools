from __future__ import annotations

from pathlib import Path

import pytest

from skill_tools.models import CatalogError
from skill_tools.source import LocalSource
from skill_tools.workflows import load_workflows


def _write_skill(root: Path, path: str, name: str, *, requires: str = "none") -> None:
    skill = root / path
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\n"
        f"name: {name}\n"
        "description: fixture skill\n"
        "meta:\n"
        "  requires_skills: " + requires + "\n"
        "  requires_repo_tools: alpha-tool\n"
        "  requires_env: FIXTURE_KEY\n"
        "---\n\nFixture body.\n",
        encoding="utf-8",
    )


def _source(tmp_path: Path, workflow_yaml: str) -> LocalSource:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "ai-tools.yaml").write_text(
        "tools:\n  fixture:\n    plugins:\n      - path: skills\n        kind: plugin\n        skills_layout: direct\n",
        encoding="utf-8",
    )
    (root / "repo-workflows.yaml").write_text(workflow_yaml, encoding="utf-8")
    (root / "repo-tools.yaml").write_text(
        "tools:\n  alpha-tool:\n    path: tools/alpha\n    install: uv tool install alpha\n",
        encoding="utf-8",
    )
    (root / "tools" / "alpha").mkdir(parents=True)
    (root / "tools" / "alpha" / "README.md").write_text("alpha tool\n", encoding="utf-8")
    _write_skill(root, "skills/base/SKILL.md", "base")
    _write_skill(root, "skills/extra/SKILL.md", "extra", requires="base")
    return LocalSource(root)


def _catalog(root: Path):
    from skill_tools.catalog import discover_catalog

    return discover_catalog(LocalSource(root))


def test_load_workflows_resolves_canonical_refs_prerequisites_and_tools(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "version: 1\n"
        "workflows:\n"
        "  - id: fixture-flow\n"
        "    title: Fixture flow\n"
        "    purpose: Exercise workflow resolution\n"
        "    steps:\n"
        "      - id: collect\n"
        "        skill: skills/extra/SKILL.md\n"
        "        optional: true\n"
        "        choice: source-count\n"
        "        when: Many sources exist\n"
        "        handoff: Review collected output\n"
        "      - id: package-check\n"
        "        tool: alpha-tool\n",
    )

    workflows = load_workflows(source, _catalog(source.root))

    workflow = workflows[0]
    assert workflow.steps[0].skill == "skills/extra/SKILL.md"
    assert workflow.steps[0].optional is True
    assert workflow.steps[0].choice == "source-count"
    assert workflow.steps[0].when == "Many sources exist"
    assert workflow.steps[0].handoff == "Review collected output"
    assert workflow.steps[1].tool == "alpha-tool"
    assert workflow.required_skills == ("skills/base/SKILL.md", "skills/extra/SKILL.md")
    assert workflow.required_tools == ("alpha-tool",)
    assert workflow.required_env == ("FIXTURE_KEY",)


@pytest.mark.parametrize(
    ("workflow_yaml", "message"),
    [
        ("version: 2\nworkflows: []\n", "version"),
        (
            "version: 1\nworkflows: [{id: same, title: A, purpose: A, steps: [{id: x, tool: alpha-tool}]}, {id: same, title: B, purpose: B, steps: [{id: y, tool: alpha-tool}]}]\n",
            "duplicate",
        ),
        (
            "version: 1\nworkflows: [{id: bad, title: Bad, purpose: Bad, steps: [{id: x, skill: missing/SKILL.md}]}]\n",
            "unknown skill",
        ),
        (
            "version: 1\nworkflows: [{id: bad, title: Bad, purpose: Bad, steps: [{id: x, tool: missing}]}]\n",
            "unknown tool",
        ),
        (
            "version: 1\nworkflows: [{id: bad, title: Bad, purpose: Bad, steps: [{id: x, skill: skills/extra/SKILL.md, tool: alpha-tool}]}]\n",
            "exactly one",
        ),
    ],
)
def test_load_workflows_rejects_invalid_schema_and_references(
    tmp_path: Path, workflow_yaml: str, message: str
) -> None:
    source = _source(tmp_path, workflow_yaml)

    with pytest.raises(CatalogError, match=message):
        load_workflows(source, _catalog(source.root))


def test_load_workflows_rejects_skill_prerequisite_cycles(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "version: 1\nworkflows: [{id: flow, title: Flow, purpose: Flow, steps: [{id: use, skill: skills/extra/SKILL.md}]}]\n",
    )
    _write_skill(source.root, "skills/base/SKILL.md", "base", requires="extra")

    with pytest.raises(CatalogError, match="cycle"):
        load_workflows(source, _catalog(source.root))


def test_load_workflows_ignores_cycles_outside_selected_workflow_closure(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "version: 1\nworkflows: [{id: flow, title: Flow, purpose: Flow, steps: [{id: use, skill: skills/base/SKILL.md}]}]\n",
    )
    _write_skill(source.root, "skills/extra/SKILL.md", "extra", requires="extra")

    workflows = load_workflows(source, _catalog(source.root))

    assert workflows[0].required_skills == ("skills/base/SKILL.md",)


def test_load_workflows_keeps_namespaced_external_prerequisites_out_of_local_graph(
    tmp_path: Path,
) -> None:
    source = _source(
        tmp_path,
        "version: 1\nworkflows: [{id: flow, title: Flow, purpose: Flow, steps: [{id: use, skill: skills/extra/SKILL.md}]}]\n",
    )
    _write_skill(
        source.root,
        "skills/extra/SKILL.md",
        "extra",
        requires="base, external-plugin:style-guide",
    )

    workflows = load_workflows(source, _catalog(source.root))

    assert workflows[0].required_skills == (
        "skills/base/SKILL.md",
        "skills/extra/SKILL.md",
    )


def test_load_workflows_keeps_non_catalog_prerequisites_external(tmp_path: Path) -> None:
    source = _source(
        tmp_path,
        "version: 1\nworkflows: [{id: flow, title: Flow, purpose: Flow, steps: [{id: use, skill: skills/extra/SKILL.md}]}]\n",
    )
    _write_skill(source.root, "skills/extra/SKILL.md", "extra", requires="configuring-settings")

    workflows = load_workflows(source, _catalog(source.root))

    assert workflows[0].required_skills == ("skills/extra/SKILL.md",)
