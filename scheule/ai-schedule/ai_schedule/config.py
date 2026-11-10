"""スケジュール設定YAMLの読み込みとバリデーション。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

VALID_DAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class JobSchedule(BaseModel):
    """1ジョブ分の実行周期。``type`` によって必須フィールドが変わる。"""

    type: Literal["daily", "weekly", "interval"]
    time: str | None = None
    days: list[str] | None = None
    minutes: int | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> JobSchedule:
        if self.type == "daily":
            self._require_time()
            self._forbid("days", "minutes")
        elif self.type == "weekly":
            self._require_time()
            if not self.days:
                raise ValueError("schedule.type=weekly には days が必要です")
            unknown = [d for d in self.days if d.upper() not in VALID_DAYS]
            if unknown:
                raise ValueError(f"不明な曜日です: {unknown} (使用可能: {sorted(VALID_DAYS)})")
            self._forbid("minutes")
        elif self.type == "interval":
            if not self.minutes or self.minutes <= 0:
                raise ValueError("schedule.type=interval には正の minutes が必要です")
            self._forbid("time", "days")
        return self

    def _require_time(self) -> None:
        if not self.time or not TIME_PATTERN.match(self.time):
            raise ValueError(f"schedule.type={self.type} には time (HH:MM, 24時間制) が必要です")

    def _forbid(self, *fields: str) -> None:
        for field in fields:
            if getattr(self, field):
                raise ValueError(f"schedule.type={self.type} では {field} は指定できません")


class Job(BaseModel):
    """1件のスケジュールジョブ定義。"""

    name: str
    enabled: bool = True
    script: Path
    args: list[str] = Field(default_factory=list)
    schedule: JobSchedule

    @model_validator(mode="after")
    def _check_name(self) -> Job:
        if not self.name.strip() or "\\" in self.name or "/" in self.name:
            raise ValueError(
                f"name は空文字・パス区切り文字を含めない値にしてください: {self.name!r}"
            )
        return self


class ScheduleConfig(BaseModel):
    """設定YAML全体(ジョブのリスト)。"""

    jobs: list[Job] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_names(self) -> ScheduleConfig:
        names = [job.name for job in self.jobs]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"job名が重複しています: {dupes}")
        return self


def load_config(path: Path) -> ScheduleConfig:
    if not path.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ScheduleConfig.model_validate(data)
