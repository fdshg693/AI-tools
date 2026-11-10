"""todo.json の読み書きと、complete / split / plan の差し替え。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import _paths  # noqa: F401
from constants import TODO_FILE
from util.models import ModelCatalog, normalize_model


def normalize_detail(value: Any) -> str:
    """detail を 'false' / 'auto' / 'true' に正規化する。不明値は false。"""
    if value is True or value == "true":
        return "true"
    if value == "auto":
        return "auto"
    return "false"


def detail_for_json(detail: str) -> bool | str:
    if detail == "true":
        return True
    if detail == "auto":
        return "auto"
    return False


def task_id_sort_key(task: dict) -> tuple:
    tid = task.get("id", 10**9)
    try:
        return (0, int(tid))
    except (TypeError, ValueError):
        return (1, str(tid))


def next_open_task(tasks: list) -> dict | None:
    """未完了タスクのうち id が最小のものを返す。"""
    pending = [t for t in tasks if isinstance(t, dict) and t.get("status") != "done"]
    if not pending:
        return None
    return min(pending, key=task_id_sort_key)


def max_task_id(tasks: list) -> int:
    ids: list[int] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        try:
            ids.append(int(t.get("id")))
        except (TypeError, ValueError):
            continue
    return max(ids) if ids else 0


def outcome_allowed(detail: str, outcome: str) -> bool:
    """detail モードと outcome の組み合わせが契約どおりか。"""
    if detail == "true":
        return outcome == "split"
    if detail == "false":
        return outcome == "completed"
    if detail == "auto":
        return outcome in ("completed", "split")
    return False


def apply_complete(tasks: list, target_id: Any) -> list:
    """当該 id だけ done にする。他は触らない。"""
    updated = []
    for t in tasks:
        if not isinstance(t, dict):
            updated.append(t)
            continue
        item = dict(t)
        if item.get("id") == target_id:
            item["status"] = "done"
        updated.append(item)
    return updated


def _task_from_child(
    child: dict,
    task_id: int,
    fallback_model: str,
    catalog: ModelCatalog,
) -> tuple[dict | None, str | None]:
    model, err = normalize_model(child.get("model"), fallback_model, catalog)
    if err:
        return None, err
    return (
        {
            "id": task_id,
            "title": child["title"],
            "status": "pending",
            "detail": detail_for_json(child["detail"]),
            "model": model,
        },
        None,
    )


def apply_split(
    tasks: list,
    target_id: Any,
    children: list[dict],
    *,
    fallback_model: str,
    catalog: ModelCatalog,
) -> tuple[list | None, str | None]:
    """当該 id のアイテムだけを children で置き換える。id はアプリが振る。"""
    idx = next(
        (i for i, t in enumerate(tasks) if isinstance(t, dict) and t.get("id") == target_id),
        None,
    )
    if idx is None:
        return None, f"対象タスク id={target_id} が見つかりません"
    next_id = max_task_id(tasks) + 1
    inserted = []
    for child in children:
        item, err = _task_from_child(child, next_id, fallback_model, catalog)
        if err:
            return None, err
        inserted.append(item)
        next_id += 1
    return tasks[:idx] + inserted + tasks[idx + 1 :], None


def apply_plan(
    children: list[dict],
    *,
    fallback_model: str,
    catalog: ModelCatalog,
) -> tuple[list | None, str | None]:
    """初回のタスクリストをアプリが採番して作る。"""
    tasks = []
    for i, child in enumerate(children, start=1):
        item, err = _task_from_child(child, i, fallback_model, catalog)
        if err:
            return None, err
        tasks.append(item)
    return tasks, None


def save_todo(workdir: Path, tasks: list) -> None:
    path = workdir / TODO_FILE
    path.write_text(
        json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_todo_state(workdir: Path) -> dict | None:
    """todo.json を読み込む。未作成なら None、壊れていれば parse_error を返す。"""
    path = workdir / TODO_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"tasks": [], "parse_error": str(exc)}
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, list):
        return {"tasks": [], "parse_error": "todo.json に tasks リストがありません"}
    return {"tasks": tasks, "parse_error": None}


def count_done(state: dict | None) -> int:
    if not state:
        return 0
    return sum(1 for t in state["tasks"] if isinstance(t, dict) and t.get("status") == "done")


def is_all_done(state: dict | None) -> bool:
    if not state or state["parse_error"] or not state["tasks"]:
        return False
    return all(isinstance(t, dict) and t.get("status") == "done" for t in state["tasks"])


def format_tasks(state: dict | None) -> str:
    if not state:
        return "  (todo.json なし)"
    if state.get("parse_error"):
        return f"  (parse_error: {state['parse_error']})"
    if not state["tasks"]:
        return "  (tasks 空)"
    lines = []
    for t in state["tasks"]:
        if not isinstance(t, dict):
            lines.append(f"  - (不正な要素: {t!r})")
            continue
        detail = normalize_detail(t.get("detail"))
        model = t.get("model") or "-"
        lines.append(
            f"  - id={t.get('id')} status={t.get('status')} detail={detail}"
            f" model={model} {t.get('title')}"
        )
    return "\n".join(lines)
