"""``--parallel`` 時のファンアウト、1回リトライ、結果整形。"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TypedDict

from aim_cli import AimError, call_async, create_client


class ResultEntry(TypedDict):
    index: int
    prompt: str
    path: str
    resolved_path: str
    success: bool
    response: str | None
    error: str | None


def format_markdown(entries: list[ResultEntry]) -> str:
    blocks = []
    for entry in entries:
        if entry["success"]:
            body = entry["response"]
        else:
            body = f"⚠ エラー: {entry['error']}"
        blocks.append(f"## {_heading(entry)}\n\n{body}\n")
    return "\n".join(blocks)


def _heading(entry: ResultEntry) -> str:
    idx = entry["index"]
    path = entry["path"]
    if path:
        return f"{idx} · {path}"
    return str(idx)


def format_json(entries: list[ResultEntry]) -> str:
    return json.dumps(list(entries), ensure_ascii=False, indent=2)


def new_session_id() -> str:
    return str(uuid.uuid4())


def make_entry(
    raw_path: str,
    resolved_path: str,
    *,
    success: bool,
    response: str | None = None,
    error: str | None = None,
    index: int = 1,
    prompt: str = "",
) -> ResultEntry:
    return {
        "index": index,
        "prompt": prompt,
        "path": raw_path,
        "resolved_path": resolved_path,
        "success": success,
        "response": response,
        "error": error,
    }


def run_parallel(
    model_id: str,
    jobs: int,
    entries: list[ResultEntry],
    targets: list[tuple[int, str]],
    *,
    web: bool = False,
    session_id: str | None = None,
) -> list[ResultEntry]:
    """各メッセージへのAI呼び出しを並行実行し、``entries`` を更新して返す。"""
    if not targets:
        return entries
    sid = session_id if session_id is not None else new_session_id()
    results = asyncio.run(_run_all_async(model_id, jobs, entries, targets, web=web, session_id=sid))
    for idx, success, result in results:
        entries[idx]["success"] = success
        if success:
            entries[idx]["response"] = result
        else:
            entries[idx]["error"] = result
    return entries


async def _run_all_async(
    model_id: str,
    jobs: int,
    entries: list[ResultEntry],
    targets: list[tuple[int, str]],
    *,
    web: bool,
    session_id: str,
) -> list[tuple[int, bool, str]]:
    semaphore = asyncio.Semaphore(jobs)

    async def worker(client, idx: int, message: str) -> tuple[int, bool, str]:
        async with semaphore:
            entry = entries[idx]
            trace: dict[str, str] = {
                "tool": "aim-cli",
                "prompt_index": str(entry["index"]),
            }
            if entry["path"]:
                trace["file_path"] = entry["path"]
            success, result = await ask_once_async(
                client,
                model_id,
                message,
                web=web,
                session_id=session_id,
                trace=trace,
            )
        return idx, success, result

    async with create_client() as client:
        return list(
            await asyncio.gather(*(worker(client, idx, message) for idx, message in targets))
        )


async def ask_once_async(
    client,
    model_id: str,
    message: str,
    *,
    web: bool = False,
    session_id: str | None = None,
    trace: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """1プロンプト分のAI呼び出しを試みる。失敗時は1回までリトライする。"""
    last_error = ""
    for _attempt in range(2):
        try:
            return True, await _call_once_async(
                client,
                model_id,
                message,
                web=web,
                session_id=session_id,
                trace=trace,
            )
        except AimError as exc:
            last_error = f"OpenRouter API呼び出しが失敗しました: {exc}"
        except _EmptyResponseError as exc:
            last_error = str(exc)
    return False, last_error


class _EmptyResponseError(Exception):
    pass


async def _call_once_async(
    client,
    model_id: str,
    message: str,
    *,
    web: bool = False,
    session_id: str | None = None,
    trace: dict[str, str] | None = None,
) -> str:
    response = (
        await call_async(
            client,
            model_id,
            message,
            web=web,
            session_id=session_id,
            trace=trace,
        )
    ).strip()
    if not response:
        raise _EmptyResponseError("OpenRouter API の応答が空でした。")
    return response
