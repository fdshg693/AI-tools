from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from vscode_profiles.cli import main


def test_version_prints_command_and_manifest_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    assert main(["--version"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [f"vscode-profiles {version}"]


def test_missing_command_returns_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage" in captured.err.lower() or "vscode-profiles" in captured.err
