"""TODO ファイル駆動の自律タスク実行ループ。

通常の AI CLI ツールではタスクごとにコンテキスト（記憶）が積み重なり、
コンパクションで圧縮してもコンテキストを完全にはクリーンにできない。
このスクリプトは Claude Agent SDK を使い、以下の仕組みでそれを解決する:

- エージェントは目標をタスクに分割して todo.json に保存する
- 1 回のエージェント呼び出しでは 1 タスクだけを完了させ、
  次タスクへの引継ぎ事項を NEXT.md に書いて終了する
- アプリ側はエージェント終了ごとに todo.json を検査し、全タスク完了まで
  **新しいセッション**（= 完全にクリーンなコンテキスト）でエージェントを呼び直す。
  その際、システムプロンプトとともに NEXT.md の内容を注入し、NEXT.md は空にする

各イテレーションは query() の新規セッションで実行されるため、
エージェントが持つ記憶は
「固定システムプロンプト + 目標 + NEXT.md の注入内容 + todo.json 等の実ファイル」
だけに限定される（セッションの resume / continue は使わない）。

使い方:
    python todo_runner/todo_runner.py "達成したい目標" [--workdir DIR] [--model haiku]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

_WRAPPER_ROOT = Path(__file__).resolve().parents[1]
if str(_WRAPPER_ROOT) not in sys.path:
    sys.path.insert(0, str(_WRAPPER_ROOT))

from util.models import load_catalog  # noqa: E402

TODO_FILE = "todo.json"
NEXT_FILE = "NEXT.md"

# 毎イテレーション共通で注入するシステムプロンプトのテンプレート。
# エージェントに課す役割:
#   1. 目標をタスク分割して todo.json を管理する
#   2. 1 回の実行では 1 タスクだけ完了させる（コンテキスト肥大化を防ぐ）
#   3. 1 タスク終わるごとに NEXT.md へ次タスクへの引継ぎ事項を書く
#
# Haiku は cwd を正しく絶対パスへ解決できず "/" 始まりのパスに迷走することが
# あるため、作業ディレクトリの絶対パスを明示し、絶対パス指定を強制する。
SYSTEM_PROMPT_TEMPLATE = """\
あなたは自律タスク実行エージェントです。
作業ディレクトリは「{workdir}」です。この中のファイルだけを操作し、
与えられた目標を段階的に完了させます。あなたのコンテキストは今回の実行限りです。
実行が終わると記憶は失われるため、続きは todo.json と NEXT.md の内容だけを頼りに
別のエージェントが引き継ぎます。

## ファイルパスの指定方法（重要）

- ファイルを読み書きするときは、必ず「{workdir}」で始まる絶対パスを使うこと。
  例: {workdir_example}
- 「/」で始まるパス（例: /todo.json, /work/todo.json）や、
  相対パス（例: ./todo.json）は絶対に使わないこと。

## 手順（必ずこの順番で行うこと）

1. 作業ディレクトリの {TODO_FILE} を確認する。
   - 存在しない場合: 目標を「1回の実行で完了できる」独立した小タスクに分割し、
     次の JSON 形式で {TODO_FILE} に保存する:
     {"tasks": [{"id": 1, "title": "タスク内容", "status": "pending"}, ...]}
     status は "pending" / "in_progress" / "done" のいずれかとする。
   - 存在する場合: それを正として扱う（勝手にタスクを追加・削除しない）。

2. 今回の実行では、未完了タスク（status が "done" でないもの）のうち
   id が最小のもの 1 つだけを実行する。複数タスクをまとめて実行してはいけない。
   - 着手時にそのタスクの status を "in_progress" に更新する。
   - 作業を完了させ、status を "done" に更新する。

3. タスクが完了したら、次の実行を担当するエージェントへの引継ぎ事項を
   {NEXT_FILE} に書く。内容は簡潔に:
   - 次に実行すべきタスクの id と概要
   - 今回作成・変更したファイルと、作業の続きに必要な事実・注意点
   あなたの記憶は引き継がれないため、{NEXT_FILE} に書かなかった情報は失われる。

4. {NEXT_FILE} を書いたら今回の実行は終了する。
   残りのタスクは次回以降の実行が担当するので、続けて実行してはいけない。

5. {TODO_FILE} の全タスクが "done" 済みなら、新たな作業はせず
   「全タスク完了」とだけ報告して終了する。

## 制約

- 使ってよいツールは Read / Write / Edit / Glob / Grep のみ。Bash は使わない。
- 作業ディレクトリ「{workdir}」の外のファイルは読み書きしない。
- {TODO_FILE} と {NEXT_FILE} は作業ディレクトリ直下に置く。
"""


def build_system_prompt(workdir: Path) -> str:
    """作業ディレクトリの絶対パスを埋め込んだシステムプロンプトを生成する。"""
    return (
        SYSTEM_PROMPT_TEMPLATE.replace("{workdir_example}", f"{workdir}\\{TODO_FILE}")
        .replace("{workdir}", str(workdir))
        .replace("{TODO_FILE}", TODO_FILE)
        .replace("{NEXT_FILE}", NEXT_FILE)
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


def read_and_clear_handoff(workdir: Path) -> str:
    """NEXT.md を読み込み、内容を返した上で空にする。"""
    path = workdir / NEXT_FILE
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8").strip()
    path.write_text("", encoding="utf-8")
    return content


def build_prompt(goal: str, workdir: Path, state: dict | None, handoff: str) -> str:
    """毎イテレーションのユーザープロンプト。NEXT.md の内容をここで注入する。"""
    parts = [f"目標: {goal}", f"作業ディレクトリ: {workdir}", ""]
    if state is None:
        parts.append(
            f"{TODO_FILE} はまだ存在しません。目標をタスクに分割して {TODO_FILE} を作成し、"
            "最初のタスクを 1 つ完了させてください。"
        )
    elif state["parse_error"]:
        parts.append(
            f"{TODO_FILE} が壊れています（{state['parse_error']}）。"
            "修復してから次の未完了タスクを 1 つ完了させてください。"
        )
    else:
        parts.append(f"{TODO_FILE} の未完了タスクのうち、次の 1 つを完了させてください。")
    parts.append("")
    if handoff:
        parts.append("前回の実行からの引継ぎ事項:")
        parts.append("---")
        parts.append(handoff)
        parts.append("---")
    else:
        parts.append("（前回からの引継ぎ事項はありません）")
    return "\n".join(parts)


def summarize_tool_input(tool_input: dict) -> str:
    text = json.dumps(tool_input, ensure_ascii=False)
    return text if len(text) <= 120 else text[:117] + "..."


async def run_agent(prompt: str, workdir: Path, model: str, max_turns: int) -> str:
    """エージェントを新規セッションで 1 回実行し、ResultMessage の subtype を返す。

    continue_conversation / resume を渡さないため、呼び出しごとに
    会話コンテキストは完全にリセットされる。
    """
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=build_system_prompt(workdir),
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
        permission_mode="acceptEdits",
        cwd=str(workdir),
        max_turns=max_turns,
        setting_sources=[],  # ユーザー/プロジェクト設定を読み込まず再現性を確保
    )

    subtype = "no_result"
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"  agent: {block.text}")
                elif isinstance(block, ToolUseBlock):
                    print(f"  [tool] {block.name}: {summarize_tool_input(block.input)}")
        elif isinstance(message, ResultMessage):
            subtype = message.subtype
            detail = ""
            if message.subtype != "success":
                detail = f" errors={message.errors}"
            elif message.is_error:
                detail = f" (warning: is_error=True, api_error_status={message.api_error_status})"
            print(
                f"  result: subtype={message.subtype} turns={message.num_turns}"
                f" cost=${message.total_cost_usd}{detail}"
            )
    return subtype


async def run(
    goal: str,
    workdir: Path,
    model: str,
    max_iterations: int,
    max_turns: int,
    max_stagnant: int,
) -> int:
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"作業ディレクトリ: {workdir}")

    stagnant = 0
    prev_done = 0

    for iteration in range(1, max_iterations + 1):
        state = load_todo_state(workdir)
        if is_all_done(state):
            print(f"\n全タスクが完了しました（{count_done(state)} タスク）。")
            return 0

        # アプリ側で TODO 状態を検査してからエージェントを呼ぶ。
        # システムプロンプトとともに NEXT.md の内容をプロンプトへ注入し、
        # NEXT.md は空にする。
        handoff = read_and_clear_handoff(workdir)
        prompt = build_prompt(goal, workdir, state, handoff)

        total = len(state["tasks"]) if state else 0
        print(f"\n=== イテレーション {iteration} (done={count_done(state)}/{total}) ===")
        subtype = await run_agent(prompt, workdir, model, max_turns)
        if subtype != "success":
            print(f"\nエージェントが異常終了しました（subtype={subtype}）。中断します。")
            return 1

        # 停滞検出: done 数が増えないまま一定回数続いたら中断する。
        done = count_done(load_todo_state(workdir))
        if done > prev_done:
            stagnant = 0
            prev_done = done
        else:
            stagnant += 1
            if stagnant >= max_stagnant:
                print(
                    f"\n{stagnant} 回連続でタスクが完了しませんでした。中断します。"
                    f"（{workdir / TODO_FILE} を確認してください）"
                )
                return 1

    print(f"\nイテレーション上限（{max_iterations} 回）に達しました。中断します。")
    return 1


def main() -> None:
    try:
        catalog = load_catalog()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"モデルカタログを読めません: {exc}") from exc

    parser = argparse.ArgumentParser(description="todo.json / NEXT.md 駆動の自律タスク実行ループ")
    parser.add_argument("goal", help="達成したい目標")
    parser.add_argument(
        "--workdir",
        default="todo_workspace",
        help="todo.json / NEXT.md / 成果物を置く作業ディレクトリ（既定: ./todo_workspace）",
    )
    parser.add_argument(
        "--model",
        default=catalog.default_id,
        help=(f"モデル（既定: {catalog.default_id}）。許可: {catalog.allowed_text()}"),
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
        help="完了タスク数が増えないまま許容する連続回数（既定: 3）",
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
        )
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
