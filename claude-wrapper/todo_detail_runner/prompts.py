"""システムプロンプトと、1 件（または初回 plan）向けユーザープロンプト。"""

from __future__ import annotations

import json
from pathlib import Path

import _paths  # noqa: F401
from constants import NEXT_FILE, RESULT_FILE, TODO_FILE
from todo_state import detail_for_json, normalize_detail
from util.models import ModelCatalog

SYSTEM_PROMPT_TEMPLATE = """\
あなたは自律タスク実行エージェントです。
作業ディレクトリは「{workdir}」です。この中のファイルだけを操作します。
あなたのコンテキストは今回の実行限りです。実行が終わると記憶は失われます。

## ファイルパスの指定方法（重要）

- ファイルを読み書きするときは、必ず「{workdir}」で始まる絶対パスを使うこと。
  例: {workdir_example}
- 「/」で始まるパスや相対パスは使わないこと。

## todo.json は触らない

TODO リスト全体はアプリが管理する。{TODO_FILE} は読んでも書いてはいけない
（ツールは拒否される）。渡された 1 件以外のタスクの存在を仮定して書き換えるな。

## 結果の出し方

処理結果は {RESULT_FILE} に JSON で書く。id や status は書いてはいけない
（アプリが振る）。detail は false / "auto" / true。model はカタログの id
だけ（省略時は親タスク、初回 plan では CLI 既定をアプリが入れる）。

実行完了:
{{"action": "complete"}}

詳細化（元の 1 件を子タスクへ分割。2 件以上。作業はしない）:
{{"action": "split", "tasks": [{{"title": "子タスク", "detail": false, "model": "haiku"}}, ...]}}

初回のタスク分割（プロンプトで指示されたときだけ。作業はしない）:
{{"action": "plan", "tasks": [{{"title": "タスク", "detail": "auto", "model": "sonnet"}}, ...]}}

complete と split を同じ実行で出してはいけない。split/plan の tasks に
id・status を付けてはいけない。カタログにない model はアプリが拒否する。

## 手順

1. ユーザープロンプトの「今回の対象」に従う。対象が 1 タスクならその detail で
   complete か split の一方。対象が「初回 plan」なら plan だけ。
2. detail=true → split のみ（成果物を書かない）。
   detail=false → 作業して complete（split 禁止）。
   detail=auto → どちらか一方。
3. 終わったら {NEXT_FILE} に引継ぎを書く（今回が complete か split か、
   作ったファイル、続きに必要な事実）。次タスクの id は知らなくてよい。
4. {NEXT_FILE} と {RESULT_FILE} を書いたら終了する。続けて別タスクをやるな。

## 制約

- 使ってよいツールは Read / Write / Edit / Glob / Grep のみ。Bash は使わない。
- 作業ディレクトリ「{workdir}」の外は読み書きしない。
- {TODO_FILE} は禁止。{RESULT_FILE} と {NEXT_FILE} と成果物だけ書いてよい。
"""


def build_system_prompt(workdir: Path) -> str:
    """作業ディレクトリの絶対パスを埋め込んだシステムプロンプトを生成する。"""
    return (
        SYSTEM_PROMPT_TEMPLATE.replace("{workdir_example}", f"{workdir}\\{RESULT_FILE}")
        .replace("{workdir}", str(workdir))
        .replace("{TODO_FILE}", TODO_FILE)
        .replace("{NEXT_FILE}", NEXT_FILE)
        .replace("{RESULT_FILE}", RESULT_FILE)
    )


def public_task(task: dict, model: str) -> dict:
    """エージェントへ渡す 1 件。リスト全体は含めない。"""
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "status": task.get("status"),
        "detail": detail_for_json(normalize_detail(task.get("detail"))),
        "model": model,
    }


def _detail_instruction(detail: str) -> str:
    if detail == "true":
        return (
            f'detail=true のため作業はせず、{RESULT_FILE} に {{"action": "split", "tasks": [...]}} '
            f"だけ書いて終了すること。{TODO_FILE} は触るな。"
        )
    if detail == "auto":
        return (
            f'detail="auto" のため、作業して {{"action": "complete"}} か、'
            f'分割して {{"action": "split", "tasks": [...]}} の一方だけ。両方は禁止。'
        )
    return (
        f'detail=false のため作業を完了し、{RESULT_FILE} に {{"action": "complete"}} と書くこと。'
        "split は禁止。"
    )


def build_prompt(
    goal: str,
    workdir: Path,
    state: dict | None,
    handoff: str,
    target: dict | None,
    *,
    catalog: ModelCatalog,
    fallback_model: str,
    resolved_model: str | None,
) -> str:
    """対象 1 件（または初回 plan）だけを渡す。todo.json 全体は渡さない。"""
    parts = [f"目標: {goal}", f"作業ディレクトリ: {workdir}", ""]
    parts.append(catalog.prompt_block())
    parts.append(
        f"model を省略した子タスクにはアプリが `{fallback_model}` "
        "（split では親タスクの model）を入れる。"
    )
    parts.append("")
    if state is None:
        parts.append("今回の対象: 初回 plan。")
        parts.append(
            f'{RESULT_FILE} に {{"action": "plan", "tasks": [...]}} だけ書いて終了すること。'
            '各タスクに detail（false / "auto" / true）と、カタログの model id を付ける。'
            '1回で完了できるなら false、判断を任せるなら "auto"、'
            "先に分割すべき入れ物なら true。難しさに合わせて model を選ぶ。"
            f"省略時の model は `{fallback_model}`。"
            "この実行では作業も split もするな。"
        )
    elif state["parse_error"]:
        parts.append(
            f"{TODO_FILE} が壊れているため作業できない。アプリ側の問題として終了してよい。"
        )
    elif target is None:
        parts.append("未完了タスクはない。何もせず終了してよい。")
    else:
        detail = normalize_detail(target.get("detail"))
        model = resolved_model or fallback_model
        parts.append("今回あなたが扱ってよい TODO は次の 1 件だけです。")
        parts.append("```json")
        parts.append(json.dumps(public_task(target, model), ensure_ascii=False, indent=2))
        parts.append("```")
        parts.append("")
        parts.append(_detail_instruction(detail))
        if detail in ("true", "auto"):
            parts.append(
                "split する場合、各子タスクにカタログの model を付ける。"
                f"省略時は親の `{model}` を引き継ぐ。"
            )
    parts.append("")
    if handoff:
        parts.append("前回の実行からの引継ぎ事項:")
        parts.append("---")
        parts.append(handoff)
        parts.append("---")
    else:
        parts.append("（前回からの引継ぎ事項はありません）")
    return "\n".join(parts)
