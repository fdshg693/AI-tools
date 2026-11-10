"""RESULT.json の契約解釈と、NEXT.md / RESULT.json の読み書き。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import _paths  # noqa: F401
from constants import NEXT_FILE, RESULT_FILE
from todo_state import (
    apply_complete,
    apply_plan,
    apply_split,
    normalize_detail,
    outcome_allowed,
    save_todo,
)
from util.models import ModelCatalog, resolve_task_model


def parse_agent_children(raw_tasks: Any) -> tuple[list[dict], str | None]:
    """エージェントが返した tasks から title/detail/model だけを取り出す。"""
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return [], "tasks が空です"
    children: list[dict] = []
    for item in raw_tasks:
        if not isinstance(item, dict):
            return [], "tasks の要素がオブジェクトではありません"
        title = str(item.get("title") or "").strip()
        if not title:
            return [], "title が空のタスクがあります"
        children.append(
            {
                "title": title,
                "detail": normalize_detail(item.get("detail")),
                "model": item.get("model"),
            }
        )
    return children, None


def parse_result(data: Any) -> tuple[str | None, list[dict], str | None]:
    """RESULT.json を (action, children, error) に分解する。

    action は plan / split / complete。children は plan/split のときだけ入る。
    complete なのに tasks がある、split/plan なのに不足、は error。
    """
    if not isinstance(data, dict):
        return None, [], "RESULT.json がオブジェクトではありません"
    action = data.get("action")
    if action not in ("complete", "split", "plan"):
        return None, [], f"不明な action: {action!r}"
    has_tasks = "tasks" in data and data["tasks"] not in (None, [])
    if action == "complete":
        if has_tasks:
            return "both", [], "complete と tasks を同時に出してはいけない"
        return "complete", [], None
    children, err = parse_agent_children(data.get("tasks"))
    if err:
        return action, [], err
    if action == "split" and len(children) < 2:
        return action, [], "split は 2 件以上必要です"
    return action, children, None


def read_and_clear_handoff(workdir: Path) -> str:
    """NEXT.md を読み込み、内容を返した上で空にする。"""
    path = workdir / NEXT_FILE
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8").strip()
    path.write_text("", encoding="utf-8")
    return content


def clear_result_file(workdir: Path) -> None:
    path = workdir / RESULT_FILE
    if path.exists():
        path.unlink()


def load_result_file(workdir: Path) -> Any | None:
    path = workdir / RESULT_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"_parse_error": str(exc)}


def apply_result_to_todo(
    workdir: Path,
    state: dict | None,
    target: dict | None,
    detail: str,
    raw: Any,
    *,
    catalog: ModelCatalog,
    fallback_model: str,
) -> str | None:
    """RESULT.json の内容を todo.json に反映し、outcome を返す。"""
    if raw is None:
        print("RESULT.json がありません。", flush=True)
        action, children, result_error = None, [], "RESULT.json がない"
    elif isinstance(raw, dict) and raw.get("_parse_error"):
        action, children, result_error = None, [], raw["_parse_error"]
    else:
        action, children, result_error = parse_result(raw)

    outcome = None
    if result_error:
        print(f"RESULT 不正: {result_error}", flush=True)
    elif action == "plan":
        if state is not None:
            print("RESULT 不正: todo.json があるのに plan は受けない。", flush=True)
        else:
            tasks, err = apply_plan(children, fallback_model=fallback_model, catalog=catalog)
            if err:
                print(f"RESULT 不正: {err}", flush=True)
            else:
                save_todo(workdir, tasks)
                outcome = "plan"
    elif target is None:
        print("RESULT 不正: 対象タスクがないのに complete/split は受けない。", flush=True)
    elif action == "complete":
        if not outcome_allowed(detail, "completed"):
            print(f"契約違反: detail={detail} なのに complete。", flush=True)
        else:
            save_todo(workdir, apply_complete(state["tasks"], target.get("id")))
            outcome = "completed"
    elif action == "split":
        if not outcome_allowed(detail, "split"):
            print(f"契約違反: detail={detail} なのに split。", flush=True)
        else:
            parent_model, model_err = resolve_task_model(target, fallback_model, catalog)
            if model_err:
                print(f"RESULT 不正: 親タスクの {model_err}", flush=True)
            else:
                tasks, err = apply_split(
                    state["tasks"],
                    target.get("id"),
                    children,
                    fallback_model=parent_model or fallback_model,
                    catalog=catalog,
                )
                if err:
                    print(f"RESULT 不正: {err}", flush=True)
                else:
                    save_todo(workdir, tasks)
                    outcome = "split"
    elif action == "both":
        print("契約違反: complete と split の両方。", flush=True)
    return outcome
