from __future__ import annotations

import pytest

from issue_agent import dispatch


def test_resolve_tool_label_returns_single_match() -> None:
    assert dispatch.resolve_tool_label(["tool:claude-code", "bug"]) == "tool:claude-code"


def test_resolve_tool_label_raises_when_missing() -> None:
    with pytest.raises(dispatch.DispatchError):
        dispatch.resolve_tool_label(["bug"])


def test_resolve_tool_label_raises_when_multiple() -> None:
    with pytest.raises(dispatch.DispatchError):
        dispatch.resolve_tool_label(["tool:claude-code", "tool:codex"])


def test_resolve_model_label_defaults_when_absent() -> None:
    assert dispatch.resolve_model_label(["tool:claude-code"]) == dispatch.DEFAULT_MODEL_ALIAS


def test_resolve_model_label_returns_known_alias() -> None:
    assert dispatch.resolve_model_label(["tool:claude-code", "model:opus"]) == "opus"


def test_resolve_model_label_raises_for_unknown_alias() -> None:
    with pytest.raises(dispatch.DispatchError):
        dispatch.resolve_model_label(["model:unknown-model"])


def test_resolve_model_label_raises_when_multiple() -> None:
    with pytest.raises(dispatch.DispatchError):
        dispatch.resolve_model_label(["model:sonnet", "model:opus"])


def test_resolve_handler_returns_claude_code_handler() -> None:
    assert dispatch.resolve_handler("tool:claude-code") is dispatch.run_claude_code


def test_resolve_handler_raises_for_unsupported_tool() -> None:
    with pytest.raises(dispatch.DispatchError):
        dispatch.resolve_handler("tool:codex")
