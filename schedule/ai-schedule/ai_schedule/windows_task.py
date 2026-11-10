"""Windows タスクスケジューラ(schtasks.exe)とのやり取り。"""

from __future__ import annotations

import csv
import io
import subprocess

from .config import Job

TASK_FOLDER = "AI-Schedule"


def task_path(name: str) -> str:
    return f"\\{TASK_FOLDER}\\{name}"


def build_run_command(job: Job) -> str:
    """タスクに登録する実行コマンド文字列(schtasks の /TR に渡す値)を組み立てる。"""
    parts = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(job.script),
        *job.args,
    ]
    return subprocess.list2cmdline(parts)


def _schedule_args(job: Job) -> list[str]:
    schedule = job.schedule
    if schedule.type == "daily":
        return ["/SC", "DAILY", "/ST", schedule.time]
    if schedule.type == "weekly":
        return [
            "/SC",
            "WEEKLY",
            "/D",
            ",".join(d.upper() for d in schedule.days),
            "/ST",
            schedule.time,
        ]
    return ["/SC", "MINUTE", "/MO", str(schedule.minutes)]


def create_or_update_task(job: Job) -> None:
    """タスクを作成する。既に存在する場合は ``/F`` により上書きする。"""
    cmd = [
        "schtasks",
        "/Create",
        "/TN",
        task_path(job.name),
        "/TR",
        build_run_command(job),
        *_schedule_args(job),
        "/F",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"タスク登録に失敗しました ({job.name}): {result.stderr.strip()}")


def delete_task(name: str) -> None:
    cmd = ["schtasks", "/Delete", "/TN", task_path(name), "/F"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"タスク削除に失敗しました ({name}): {result.stderr.strip()}")


def list_registered_names() -> list[str]:
    """``\\AI-Schedule\\`` 配下に登録済みのジョブ名一覧を返す。

    ``/NH`` (ヘッダー無し) + CSV 出力を使うことで、システムのロケールによって
    列見出し("TaskName" / "タスク名" 等)が変わる問題を回避している。
    """
    result = subprocess.run(
        ["schtasks", "/Query", "/FO", "CSV", "/NH"], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"タスク一覧の取得に失敗しました: {result.stderr.strip()}")

    prefix = task_path("")
    names = []
    for row in csv.reader(io.StringIO(result.stdout)):
        if row and row[0].startswith(prefix):
            names.append(row[0][len(prefix) :])
    return names
