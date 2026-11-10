from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_schedule.config import Job, JobSchedule
from ai_schedule.windows_task import (
    build_run_command,
    create_or_update_task,
    delete_task,
    list_registered_names,
    task_path,
)


def make_job(**overrides) -> Job:
    defaults = dict(
        name="my-job",
        script=Path("C:/scripts/foo.ps1"),
        schedule=JobSchedule(type="daily", time="09:00"),
    )
    defaults.update(overrides)
    return Job(**defaults)


def test_task_path_uses_ai_schedule_folder() -> None:
    assert task_path("my-job") == "\\AI-Schedule\\my-job"


def test_build_run_command_wraps_script_in_powershell() -> None:
    job = make_job(args=["-Foo", "bar with space"])
    command = build_run_command(job)
    assert command.startswith("powershell.exe -NoProfile -ExecutionPolicy Bypass -File")
    assert "foo.ps1" in command
    assert '"bar with space"' in command


class FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_create_or_update_task_builds_schtasks_create_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    create_or_update_task(make_job())

    cmd = captured["cmd"]
    assert cmd[:2] == ["schtasks", "/Create"]
    assert "/TN" in cmd and "\\AI-Schedule\\my-job" in cmd
    assert "/F" in cmd
    assert "/SC" in cmd and "DAILY" in cmd


def test_create_or_update_task_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kw: FakeCompletedProcess(returncode=1, stderr="boom")
    )
    with pytest.raises(RuntimeError, match="boom"):
        create_or_update_task(make_job())


def test_delete_task_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kw: FakeCompletedProcess(returncode=1, stderr="nope")
    )
    with pytest.raises(RuntimeError, match="nope"):
        delete_task("my-job")


def test_list_registered_names_filters_by_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    csv_output = (
        '"\\AI-Schedule\\job-a","2026-07-27 09:00:00","Ready"\r\n'
        '"\\Other-Folder\\job-b","N/A","Ready"\r\n'
        '"\\AI-Schedule\\job-c","N/A","Disabled"\r\n'
    )
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kw: FakeCompletedProcess(returncode=0, stdout=csv_output)
    )
    assert list_registered_names() == ["job-a", "job-c"]


def test_list_registered_names_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kw: FakeCompletedProcess(returncode=1, stderr="denied")
    )
    with pytest.raises(RuntimeError, match="denied"):
        list_registered_names()
