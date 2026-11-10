from __future__ import annotations

from ona_run_cli import (
    AGENT_TEMPLATES,
    build_exec_argv,
    needs_task,
    resolve_template,
    split_command_argv,
)


def test_split_command_argv_without_command_returns_none() -> None:
    argv = ["repo", "task", "--agent", "claude"]
    parser_argv, command = split_command_argv(argv)
    assert parser_argv == argv
    assert command is None


def test_split_command_argv_extracts_tokens_after_marker() -> None:
    argv = ["repo", "task", "--cleanup", "stop", "--command", "claude", "-p", "{task}"]
    parser_argv, command = split_command_argv(argv)
    assert parser_argv == ["repo", "task", "--cleanup", "stop"]
    assert command == ["claude", "-p", "{task}"]


def test_split_command_argv_with_no_tokens_after_marker_returns_empty_list() -> None:
    argv = ["repo", "task", "--command"]
    parser_argv, command = split_command_argv(argv)
    assert parser_argv == ["repo", "task"]
    assert command == []


def test_resolve_template_prefers_explicit_command_over_agent() -> None:
    custom = ["echo", "{task}"]
    assert resolve_template("claude", custom) == custom


def test_resolve_template_falls_back_to_agent_preset() -> None:
    assert resolve_template("claude", None) == AGENT_TEMPLATES["claude"]


def test_needs_task_detects_placeholder() -> None:
    assert needs_task(["claude", "-p", "{task}"]) is True
    assert needs_task(["npm", "test"]) is False


def test_build_exec_argv_substitutes_placeholder_in_every_token() -> None:
    template = ["claude", "-p", "{task}", "--dangerously-skip-permissions"]
    argv = build_exec_argv(template, "fix the README typo")
    assert argv == ["claude", "-p", "fix the README typo", "--dangerously-skip-permissions"]


def test_build_exec_argv_substitutes_placeholder_inside_a_longer_token() -> None:
    template = ["run-agent", "--prompt={task}"]
    argv = build_exec_argv(template, "do the thing")
    assert argv == ["run-agent", "--prompt=do the thing"]


def test_build_exec_argv_leaves_template_unchanged_when_task_is_none() -> None:
    template = ["npm", "test"]
    assert build_exec_argv(template, None) == template


def test_build_exec_argv_does_not_mutate_input_template() -> None:
    template = ["claude", "-p", "{task}"]
    build_exec_argv(template, "hello")
    assert template == ["claude", "-p", "{task}"]
