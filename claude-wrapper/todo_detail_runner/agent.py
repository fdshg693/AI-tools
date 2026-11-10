"""PreToolUse フックと Claude Agent SDK の 1 回実行。"""

from __future__ import annotations

import json
from pathlib import Path

from constants import PROTECTED_BASENAMES, RESULT_FILE, TODO_FILE
from prompts import build_system_prompt


def tool_input_paths(tool_input: dict) -> list[str]:
    paths: list[str] = []
    for key in ("file_path", "path", "notebook_path"):
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            paths.append(val)
    return paths


def touches_protected_todo(tool_input: dict) -> bool:
    """ツール引数が todo.json 自体を指しているか。"""
    for raw in tool_input_paths(tool_input):
        name = Path(raw.replace("\\", "/")).name.lower()
        if name in PROTECTED_BASENAMES:
            return True
    return False


def summarize_tool_input(tool_input: dict) -> str:
    text = json.dumps(tool_input, ensure_ascii=False)
    return text if len(text) <= 120 else text[:117] + "..."


async def deny_todo_json_hook(
    input_data: dict,
    tool_use_id: str | None,
    context: dict,
) -> dict:
    """todo.json への Read/Write/Edit/Grep/Glob を拒否する。"""
    del tool_use_id, context
    tool_input = input_data.get("tool_input") or {}
    if not isinstance(tool_input, dict) or not touches_protected_todo(tool_input):
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"{TODO_FILE} はアプリ専用です。結果は {RESULT_FILE} に書いてください。"
            ),
        }
    }


async def run_agent(prompt: str, workdir: Path, model: str, max_turns: int) -> str:
    """エージェントを新規セッションで 1 回実行し、ResultMessage の subtype を返す。"""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        HookMatcher,
        ResultMessage,
        TextBlock,
        ToolUseBlock,
        query,
    )

    options = ClaudeAgentOptions(
        model=model,
        system_prompt=build_system_prompt(workdir),
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
        permission_mode="acceptEdits",
        cwd=str(workdir),
        max_turns=max_turns,
        setting_sources=[],
        hooks={
            "PreToolUse": [
                HookMatcher(
                    matcher="Read|Write|Edit|Glob|Grep",
                    hooks=[deny_todo_json_hook],
                )
            ]
        },
    )

    subtype = "no_result"
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"  agent: {block.text}", flush=True)
                elif isinstance(block, ToolUseBlock):
                    print(
                        f"  [tool] {block.name}: {summarize_tool_input(block.input)}",
                        flush=True,
                    )
        elif isinstance(message, ResultMessage):
            subtype = message.subtype
            detail = ""
            if message.subtype != "success":
                detail = f" errors={message.errors}"
            elif message.is_error:
                detail = f" (warning: is_error=True, api_error_status={message.api_error_status})"
            print(
                f"  result: subtype={message.subtype} turns={message.num_turns}"
                f" cost=${message.total_cost_usd}{detail}",
                flush=True,
            )
    return subtype
