#!/usr/bin/env python3
"""Dump past task-tracker session transcripts (user/assistant text only) to a
Grep-able markdown file.

Self-contained (stdlib only): this does not import
`claude-code-debugging/scripts/extract_log.py` on purpose, so task-tracker
keeps working even if that skill is renamed, moved, or removed later. See
../memo/decisions.md #4.

Usage:
    python dump_sessions.py <task-name> [--project-dir PATH]

Reads `.claude/tasks/<task-name>/sessions.md` for the list of session ids
recorded by the task-tracker hook, finds each session's transcript under
`~/.claude/projects/*/<session-id>.jsonl` (the project-directory segment is
wildcarded because the same working directory can appear under different
casing, e.g. a lowercased drive letter -- session ids are UUID-like and
unique enough on their own), extracts user/assistant text (tool_use/
tool_result content is skipped -- it can be huge and isn't useful for a
"what did we discuss" search), and writes the result to
`.claude/tasks/<task-name>/temp/dump_<timestamp>.md`.

Session ids referenced in sessions.md but not found anywhere are reported as
warnings -- never silently dropped.
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

SESSION_LINE_RE = re.compile(r"^-\s+\S+\s+(\S+)\s*$")


def read_session_ids(sessions_path):
    if not sessions_path.exists():
        sys.exit(f"error: {sessions_path} が見つかりません")
    ids = []
    with sessions_path.open("r", encoding="utf-8") as f:
        for line in f:
            m = SESSION_LINE_RE.match(line.rstrip("\n"))
            if m:
                ids.append(m.group(1))
    return ids


def find_transcript(session_id):
    pattern = str(Path.home() / ".claude" / "projects" / "*" / f"{session_id}.jsonl")
    matches = glob.glob(pattern)
    return matches[0] if matches else None


def extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return ""


def dump_session(path, session_id, out):
    out.write(f"## Session {session_id}\n\n")
    out.write(f"source: {path}\n\n")
    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                print(f"warning: {path}:{lineno} をパースできませんでした", file=sys.stderr)
                continue

            msg_type = obj.get("type")
            if msg_type not in ("user", "assistant"):
                continue

            message = obj.get("message") or {}
            text = extract_text(message.get("content"))
            if not text.strip():
                continue

            timestamp = obj.get("timestamp", "")
            out.write(f"### {msg_type} {timestamp}\n\n{text}\n\n")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("task_name", help="タスク名（.claude/tasks/<task_name>/ に対応）")
    parser.add_argument(
        "--project-dir",
        default=os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(),
        help="リポジトリのルート（省略時はCLAUDE_PROJECT_DIR環境変数、なければカレントディレクトリ）",
    )
    args = parser.parse_args()

    task_dir = Path(args.project_dir) / ".claude" / "tasks" / args.task_name
    sessions_path = task_dir / "sessions.md"
    session_ids = read_session_ids(sessions_path)
    if not session_ids:
        sys.exit(f"error: {sessions_path} にセッションIDが見つかりませんでした")

    temp_dir = task_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    out_path = temp_dir / f"dump_{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"

    not_found = []
    with out_path.open("w", encoding="utf-8") as out:
        out.write(f"# task-tracker dump: {args.task_name}\n\n")
        for session_id in session_ids:
            path = find_transcript(session_id)
            if path is None:
                not_found.append(session_id)
                continue
            dump_session(path, session_id, out)

        if not_found:
            out.write("## 見つからなかったセッションID\n\n")
            for session_id in not_found:
                out.write(f"- {session_id}\n")

    found_count = len(session_ids) - len(not_found)
    print(f"書き出し完了: {out_path} ({found_count}/{len(session_ids)} セッション)")
    if not_found:
        print(
            f"警告: {len(not_found)}件のセッションが見つかりませんでした: {', '.join(not_found)}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
