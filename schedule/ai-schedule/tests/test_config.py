from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from ai_schedule.config import load_config


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "jobs.yaml")


def test_load_config_empty_file_has_no_jobs(tmp_path: Path) -> None:
    config = load_config(write(tmp_path / "jobs.yaml", ""))
    assert config.jobs == []


def test_load_config_parses_daily_job(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path / "jobs.yaml",
            """
            jobs:
              - name: my-job
                script: C:\\scripts\\foo.ps1
                args: ["-Foo", "bar"]
                schedule:
                  type: daily
                  time: "09:00"
            """,
        )
    )
    assert len(config.jobs) == 1
    job = config.jobs[0]
    assert job.name == "my-job"
    assert job.enabled is True
    assert job.args == ["-Foo", "bar"]
    assert job.schedule.type == "daily"
    assert job.schedule.time == "09:00"


def test_load_config_parses_weekly_job(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path / "jobs.yaml",
            """
            jobs:
              - name: my-job
                script: C:\\scripts\\foo.ps1
                schedule:
                  type: weekly
                  time: "22:30"
                  days: [mon, WED]
            """,
        )
    )
    assert config.jobs[0].schedule.days == ["mon", "WED"]


def test_load_config_parses_interval_job(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path / "jobs.yaml",
            """
            jobs:
              - name: my-job
                script: C:\\scripts\\foo.ps1
                schedule:
                  type: interval
                  minutes: 15
            """,
        )
    )
    assert config.jobs[0].schedule.minutes == 15


INVALID_SCHEDULES = [
    pytest.param({"type": "daily"}, id="daily-missing-time"),
    pytest.param({"type": "daily", "time": "9:00"}, id="daily-non-24h-time"),
    pytest.param({"type": "daily", "time": "09:00", "minutes": 5}, id="daily-forbids-minutes"),
    pytest.param({"type": "weekly", "time": "09:00"}, id="weekly-missing-days"),
    pytest.param({"type": "weekly", "time": "09:00", "days": ["XXX"]}, id="weekly-unknown-day"),
    pytest.param({"type": "interval"}, id="interval-missing-minutes"),
    pytest.param({"type": "interval", "minutes": 0}, id="interval-non-positive-minutes"),
    pytest.param({"type": "interval", "minutes": 5, "time": "09:00"}, id="interval-forbids-time"),
]


@pytest.mark.parametrize("schedule", INVALID_SCHEDULES)
def test_load_config_rejects_invalid_schedule(tmp_path: Path, schedule: dict) -> None:
    data = {"jobs": [{"name": "my-job", "script": "C:\\scripts\\foo.ps1", "schedule": schedule}]}
    path = write(tmp_path / "jobs.yaml", yaml.safe_dump(data))
    with pytest.raises(ValidationError):
        load_config(path)


def test_load_config_rejects_name_with_path_separator(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_config(
            write(
                tmp_path / "jobs.yaml",
                """
                jobs:
                  - name: bad/name
                    script: C:\\scripts\\foo.ps1
                    schedule:
                      type: daily
                      time: "09:00"
                """,
            )
        )


def test_load_config_rejects_duplicate_names(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_config(
            write(
                tmp_path / "jobs.yaml",
                """
                jobs:
                  - name: dup
                    script: C:\\scripts\\a.ps1
                    schedule:
                      type: daily
                      time: "09:00"
                  - name: dup
                    script: C:\\scripts\\b.ps1
                    schedule:
                      type: interval
                      minutes: 5
                """,
            )
        )
