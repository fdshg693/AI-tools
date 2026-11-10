"""detail フィールド付き TODO 駆動の自律タスク実行ループ。

todo.json はアプリが所有する。エージェントには今回の 1 タスクだけを渡し、
結果は RESULT.json（complete / split / plan）で受け取る。todo.json への
Read/Write/Edit はフックで拒否する。

detail モード:
- false: そのタスクの作業を実行して complete（分割しない）
- true:  作業はせず split。アプリが当該アイテムだけを子タスクに差し替える
- auto:  complete か split の一方。両方は禁止

使い方:
    python todo_detail_runner/todo_detail_runner.py "達成したい目標" [--workdir DIR] [--model haiku]

各タスクの model は util/models.json のカタログ id。省略時は --model。
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import _paths  # noqa: F401
from agent import run_agent, touches_protected_todo
from constants import TODO_FILE
from util.models import (
    ModelCatalog,
    invalid_tasks_model_error,
    load_catalog,
    normalize_model,
    resolve_task_model,
)
from prompts import build_prompt
from result import (
    apply_result_to_todo,
    clear_result_file,
    load_result_file,
    parse_result,
    read_and_clear_handoff,
)
from todo_state import (
    apply_complete,
    apply_plan,
    apply_split,
    count_done,
    format_tasks,
    is_all_done,
    load_todo_state,
    next_open_task,
    normalize_detail,
    outcome_allowed,
)

# unittest が `from todo_detail_runner import ...` する公開面。
__all__ = [
    "apply_complete",
    "apply_plan",
    "apply_split",
    "next_open_task",
    "normalize_detail",
    "normalize_model",
    "outcome_allowed",
    "parse_result",
    "touches_protected_todo",
]


def _progress_happened(
    prev_done: int,
    done: int,
    outcome: str | None,
) -> bool:
    if done > prev_done:
        return True
    if outcome in ("split", "plan"):
        return True
    return False


async def run(
    goal: str,
    workdir: Path,
    model: str,
    max_iterations: int,
    max_turns: int,
    max_stagnant: int,
    catalog: ModelCatalog,
) -> int:
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"作業ディレクトリ: {workdir}", flush=True)
    print(f"モデルカタログ: {catalog.allowed_text()}（省略時/CLI 既定: {model}）", flush=True)

    stagnant = 0
    prev_done = 0

    for iteration in range(1, max_iterations + 1):
        state = load_todo_state(workdir)
        if is_all_done(state):
            print(f"\n全タスクが完了しました（{count_done(state)} タスク）。", flush=True)
            return 0
        if state and state.get("parse_error"):
            print(
                f"\n{TODO_FILE} が壊れています（{state['parse_error']}）。中断します。", flush=True
            )
            return 1
        if state:
            model_error = invalid_tasks_model_error(state["tasks"], catalog)
            if model_error:
                print(
                    f"\n{TODO_FILE} の model が不正です（{model_error}）。中断します。", flush=True
                )
                return 1

        handoff = read_and_clear_handoff(workdir)
        target = next_open_task(state["tasks"]) if state else None
        resolved_model, resolve_err = resolve_task_model(target, model, catalog)
        if resolve_err:
            print(f"\n対象タスクの {resolve_err}。中断します。", flush=True)
            return 1
        task_model = resolved_model or model
        prompt = build_prompt(
            goal,
            workdir,
            state,
            handoff,
            target,
            catalog=catalog,
            fallback_model=model,
            resolved_model=task_model,
        )

        total = len(state["tasks"]) if state else 0
        detail = normalize_detail(target.get("detail")) if target else "-"
        print(
            f"\n=== イテレーション {iteration} (done={count_done(state)}/{total}) ===", flush=True
        )
        print("現在の TODO:", flush=True)
        print(format_tasks(state), flush=True)
        if target:
            print(
                f"対象: id={target.get('id')} detail={detail} model={task_model}"
                f" {target.get('title')}",
                flush=True,
            )
        elif state is None:
            print(f"対象: 初回 plan（model={task_model}）", flush=True)

        clear_result_file(workdir)
        subtype = await run_agent(prompt, workdir, task_model, max_turns)
        if subtype != "success":
            print(
                f"\nエージェントが異常終了しました（subtype={subtype}）。中断します。", flush=True
            )
            return 1

        raw = load_result_file(workdir)
        clear_result_file(workdir)
        outcome = apply_result_to_todo(
            workdir,
            state,
            target,
            detail,
            raw,
            catalog=catalog,
            fallback_model=model,
        )

        after_state = load_todo_state(workdir)
        print("更新後の TODO:", flush=True)
        print(format_tasks(after_state), flush=True)
        if outcome:
            print(f"outcome={outcome} (detail={detail}, applied_by_app=True)", flush=True)

        done = count_done(after_state)
        if _progress_happened(prev_done, done, outcome):
            stagnant = 0
            prev_done = max(prev_done, done)
        else:
            stagnant += 1
            if stagnant >= max_stagnant:
                print(
                    f"\n{stagnant} 回連続で前進しませんでした。中断します。"
                    f"（{workdir / TODO_FILE} を確認してください）",
                    flush=True,
                )
                return 1

    print(f"\nイテレーション上限（{max_iterations} 回）に達しました。中断します。", flush=True)
    return 1


def main() -> None:
    try:
        catalog = load_catalog()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"モデルカタログを読めません: {exc}") from exc

    parser = argparse.ArgumentParser(
        description="detail フィールド付き todo.json 駆動ループ（1 件だけ渡してアプリが差し替え）"
    )
    parser.add_argument("goal", help="達成したい目標")
    parser.add_argument(
        "--workdir",
        default="todo_detail_workspace",
        help="todo.json / NEXT.md / 成果物を置く作業ディレクトリ（既定: ./todo_detail_workspace、CWD 基準）",
    )
    parser.add_argument(
        "--model",
        default=catalog.default_id,
        help=(
            f"タスクに model が無いときの既定（既定: {catalog.default_id}）。"
            f"許可: {catalog.allowed_text()}"
        ),
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=20,
        help="エージェント呼び出しの上限回数（既定: 20）",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=15,
        help="1 回の実行内でのエージェントのターン上限（既定: 15）",
    )
    parser.add_argument(
        "--max-stagnant",
        type=int,
        default=3,
        help="前進しないまま許容する連続回数（既定: 3）",
    )
    args = parser.parse_args()
    if not catalog.is_allowed(args.model):
        parser.error(f"不明な --model {args.model!r}（許可: {catalog.allowed_text()}）")

    exit_code = asyncio.run(
        run(
            goal=args.goal,
            workdir=Path(args.workdir).resolve(),
            model=args.model,
            max_iterations=args.max_iterations,
            max_turns=args.max_turns,
            max_stagnant=args.max_stagnant,
            catalog=catalog,
        )
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
