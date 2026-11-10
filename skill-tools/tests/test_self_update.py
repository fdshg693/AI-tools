from __future__ import annotations

import json
from pathlib import Path

import pytest

from skill_tools import self_update
from skill_tools.cli import main
from skill_tools.models import InstallError
from skill_tools.self_update import InstallOrigin, read_install_origin, requirement_spec


class FakeDistribution:
    def __init__(self, direct_url: object | None) -> None:
        self._text = (
            None
            if direct_url is None
            else (direct_url if isinstance(direct_url, str) else json.dumps(direct_url))
        )

    def read_text(self, name: str) -> str | None:
        assert name == "direct_url.json"
        return self._text


def test_editable_install_is_detected() -> None:
    dist = FakeDistribution(
        {"url": "file:///C:/C/ai/tools/skill-tools", "dir_info": {"editable": True}}
    )
    origin = read_install_origin(dist)
    assert origin.kind == "editable"
    assert origin.editable_path == "file:///C:/C/ai/tools/skill-tools"


def test_git_install_keeps_repository_revision_and_subdirectory() -> None:
    dist = FakeDistribution(
        {
            "url": "https://github.com/me/fork.git",
            "vcs_info": {"vcs": "git", "requested_revision": "dev", "commit_id": "abc"},
            "subdirectory": "pkg/skill-tools",
        }
    )
    origin = read_install_origin(dist)
    assert origin == InstallOrigin(
        kind="git",
        url="https://github.com/me/fork.git",
        revision="dev",
        subdirectory="pkg/skill-tools",
    )
    assert (
        requirement_spec(origin)
        == "git+https://github.com/me/fork.git@dev#subdirectory=pkg/skill-tools"
    )


@pytest.mark.parametrize(
    "direct_url",
    [None, "not json", "[]", {"url": "file:///x", "dir_info": {}}, {"url": "https://x/y.whl"}],
)
def test_other_installs_fall_back_to_default_github_url(direct_url: object) -> None:
    origin = read_install_origin(FakeDistribution(direct_url))
    assert origin.kind == "other"
    assert requirement_spec(origin) == (
        "git+https://github.com/fdshg693/ai.git#subdirectory=tools/skill-tools"
    )


def test_git_install_without_revision_tracks_default_branch() -> None:
    origin = read_install_origin(
        FakeDistribution({"url": "https://github.com/fdshg693/ai", "vcs_info": {"vcs": "git"}})
    )
    assert requirement_spec(origin) == (
        "git+https://github.com/fdshg693/ai#subdirectory=tools/skill-tools"
    )


def test_uv_tool_environment_checks_receipt(tmp_path: Path) -> None:
    assert not self_update.uv_tool_environment(str(tmp_path))
    (tmp_path / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    assert self_update.uv_tool_environment(str(tmp_path))


def test_update_refuses_editable_install(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(
        self_update,
        "read_install_origin",
        lambda: InstallOrigin(kind="editable", editable_path="file:///x"),
    )
    ran: list[list[str]] = []
    monkeypatch.setattr(self_update, "run_update", ran.append)
    assert main(["self-update"], cwd=tmp_path) == 0
    assert "editable install" in capsys.readouterr().out
    assert ran == []


def test_update_dry_run_prints_command_without_running(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(self_update, "read_install_origin", lambda: InstallOrigin(kind="other"))
    monkeypatch.setattr(self_update, "uv_tool_environment", lambda prefix=None: True)
    ran: list[list[str]] = []
    monkeypatch.setattr(self_update, "run_update", ran.append)
    assert main(["self-update", "--dry-run"], cwd=tmp_path) == 0
    out = capsys.readouterr().out
    assert "uv tool install --force git+https://github.com/fdshg693/ai.git" in out
    assert ran == []


def test_update_runs_command_for_non_editable_install(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(self_update, "read_install_origin", lambda: InstallOrigin(kind="other"))
    monkeypatch.setattr(self_update, "uv_tool_environment", lambda prefix=None: True)
    monkeypatch.setattr(self_update, "locate_uv", lambda: "uv")
    ran: list[list[str]] = []
    monkeypatch.setattr(self_update, "run_update", lambda command: ran.append(command))
    assert main(["self-update"], cwd=tmp_path) == 0
    assert ran and ran[0][:4] == ["uv", "tool", "install", "--force"]
    assert "updated" in capsys.readouterr().out


def test_update_rejects_install_outside_uv_tool(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(self_update, "read_install_origin", lambda: InstallOrigin(kind="other"))
    monkeypatch.setattr(self_update, "uv_tool_environment", lambda prefix=None: False)
    assert main(["self-update"], cwd=tmp_path) == 4
    assert "uv tool install" in capsys.readouterr().err


def test_read_install_origin_rejects_missing_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str):
        raise self_update.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(self_update.metadata, "distribution", missing)
    with pytest.raises(InstallError):
        read_install_origin()
