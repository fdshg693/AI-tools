"""Workflow list and show commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..catalog import discover_catalog
from ..config import create_source
from ..models import CatalogError
from ..workflows import Workflow, load_workflows, select_workflow
from .arguments import _add_runtime_arguments, _load_runtime_config


def _add_workflow_command(commands) -> None:
    workflow = commands.add_parser("workflow", help="browse purpose-oriented skill workflows")
    subcommands = workflow.add_subparsers(dest="workflow_command", required=True)
    list_command = subcommands.add_parser("list", help="list workflows from the local source")
    _add_runtime_arguments(list_command)
    list_command.add_argument("--json", action="store_true", help="write workflows as JSON")
    show = subcommands.add_parser("show", help="show workflow steps and resolved prerequisites")
    _add_runtime_arguments(show)
    show.add_argument("id", help="workflow ID")
    show.add_argument("--json", action="store_true", help="write workflow details as JSON")


def _workflow_payload(workflow: Workflow) -> dict[str, Any]:
    return {
        "id": workflow.id,
        "title": workflow.title,
        "purpose": workflow.purpose,
        "requiresEnv": list(workflow.requires_env),
        "steps": [
            {
                "id": step.id,
                "skill": step.skill,
                "tool": step.tool,
                "optional": step.optional,
                "choice": step.choice,
                "when": step.when,
                "handoff": step.handoff,
            }
            for step in workflow.steps
        ],
        "requiredSkills": list(workflow.required_skills),
        "requiredTools": list(workflow.required_tools),
        "requiredEnv": list(workflow.required_env),
    }


def _command_workflow(args: argparse.Namespace, cwd: Path) -> int:
    config = _load_runtime_config(args, cwd)
    if config.source.type != "local":
        raise CatalogError(
            "workflow commands require a local source; GitHub sources are unsupported"
        )
    source = create_source(config)
    workflows = load_workflows(source, discover_catalog(source))
    if args.workflow_command == "list":
        if args.json:
            print(
                json.dumps(
                    [_workflow_payload(item) for item in workflows], ensure_ascii=False, indent=2
                )
            )
        else:
            print("id\ttitle\tpurpose")
            for item in workflows:
                print(f"{item.id}\t{item.title}\t{item.purpose}")
        return 0

    workflow = select_workflow(workflows, args.id)
    if args.json:
        print(json.dumps(_workflow_payload(workflow), ensure_ascii=False, indent=2))
        return 0

    print(f"{workflow.id}\t{workflow.title}")
    print(f"Purpose: {workflow.purpose}")
    print("Steps:")
    for index, step in enumerate(workflow.steps, start=1):
        reference = f"skill: {step.skill}" if step.skill is not None else f"tool: {step.tool}"
        annotations = []
        if step.optional:
            annotations.append("optional")
        if step.choice is not None:
            annotations.append(f"choice: {step.choice}")
        suffix = f" ({', '.join(annotations)})" if annotations else ""
        print(f"{index}. {step.id}\t{reference}{suffix}")
        if step.when is not None:
            print(f"   when: {step.when}")
        if step.handoff is not None:
            print(f"   handoff: {step.handoff}")
    print(f"Required skills: {', '.join(workflow.required_skills) or '(none)'}")
    print(f"Required tools: {', '.join(workflow.required_tools) or '(none)'}")
    print(f"Required environment: {', '.join(workflow.required_env) or '(none)'}")
    return 0
