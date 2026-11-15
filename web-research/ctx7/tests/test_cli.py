"""Offline tests for ``ctx7_cli``'s pure helpers: envelope shape and API-key
resolution precedence. Network-touching command handlers (``cmd_library`` /
``cmd_docs``) are exercised indirectly by ``test_client.py``'s coverage of
the ``ctx7_core.client`` functions they call; duplicating that here with
argparse plumbing would just be a thinner copy of the same assertions.
"""

from __future__ import annotations

import argparse

from ctx7_cli import build_envelope, resolve_api_key


def test_build_envelope_shape() -> None:
    envelope = build_envelope("library", 0, {"results": []})
    assert envelope == {"command": "library", "exit_code": 0, "result": {"results": []}}


def test_resolve_api_key_prefers_cli_flag_over_env(monkeypatch) -> None:
    monkeypatch.setenv("CONTEXT7_API_KEY", "from-env")
    args = argparse.Namespace(api_key="from-flag")
    assert resolve_api_key(args) == "from-flag"


def test_resolve_api_key_falls_back_to_env(monkeypatch) -> None:
    monkeypatch.setenv("CONTEXT7_API_KEY", "from-env")
    args = argparse.Namespace(api_key=None)
    assert resolve_api_key(args) == "from-env"


def test_resolve_api_key_none_when_neither_set(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)
    monkeypatch.setattr("ctx7_core.environment.ENV_PATH", tmp_path / ".env")
    args = argparse.Namespace(api_key=None)
    assert resolve_api_key(args) is None


def test_resolve_api_key_blank_flag_falls_through_to_env(monkeypatch) -> None:
    # An empty --api-key "" should not shadow a real env value.
    monkeypatch.setenv("CONTEXT7_API_KEY", "from-env")
    args = argparse.Namespace(api_key="   ")
    assert resolve_api_key(args) == "from-env"
