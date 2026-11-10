"""Fill missing SKILL.md meta fields using parallel per-skill ``aim`` calls.

The model is asked to classify each skill directory in a fixed,
line-oriented format. Existing non-empty fields are deliberately preserved
by ``ensure_meta_field``; this script only supplies missing values.

Calls run concurrently (one ``aim`` subprocess per skill directory, up
to ``--jobs`` at a time) and each skill's SKILL.md is patched and reported
as soon as its own call returns, so progress is visible incrementally
instead of only after every call in a batch has finished.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Sequence

from skill.util.meta_field_registry import get_enum
from skill.util.repo_tools_registry import load_repo_tools
from skill.util.skill_frontmatter import SkillFrontmatter, find_skill_md_files, read_frontmatter
from skill.util.skill_meta_field import ensure_meta_field

REPO_ROOT = Path(__file__).resolve().parents[4]
AIM_COMMAND = "aim"
AIM_INSTALL_HINT = "先に `uv tool install --reinstall --editable tools/aim` を実行してください。"

META_FIELDS = (
    "status",
    "requires_skills",
    "requires_hooks",
    "requires_install",
    "dependencies",
    "requires_env",
    "requires_repo_tools",
)
STATUS_ENUM = get_enum("status")


def _build_known_tools_note(tools: dict[str, dict[str, str]]) -> str:
    """Render repo-tools.yaml's tool->path mapping for the classification prompt.

    Keeps AI-filled requires_repo_tools/requires_install spellings aligned with
    repo-tools.yaml (the SSOT checked by skill.check.check_skill_repo_tools)
    instead of drifting into ad-hoc forms per skill.
    """
    if not tools:
        return ""
    lines = "\n".join(f"- {name}: {info['path']}" for name, info in sorted(tools.items()))
    return f"""
このリポジトリの既知のインストール済み外部CLIツール一覧（tools/配下、repo-tools.yamlより。
「ツール名: パス」の形式）。このスキルがこれらのいずれかに依存する場合、
requires_repo_toolsにはこの一覧の「ツール名」を、requires_installにはこの一覧の
「パス」を含めてください（未知のツールに依存する場合はこの制約に従わなくてよい）。
{lines}
"""


def _build_classification_prompt(status_enum: Sequence[str], known_tools_note: str = "") -> str:
    status_choices = "/".join(status_enum)
    return f"""\
このディレクトリ全体（ディレクトリツリーと全ファイル内容）を調査し、SKILL.mdのmeta:に追加する7フィールドを判定してください。
回答は次の7行だけにしてください。順序とフィールド名を変えず、各行を「フィールド名: 値」の形式にしてください。
該当しない場合の値は必ず none としてください。値は1行のスカラー文字列にし、複数ある場合はカンマ区切りにしてください。
statusの値は {status_choices} のいずれか1つにしてください。
Markdownのコードブロック、箇条書き、説明文、前置き、後置きは不要です。
{known_tools_note}
status: <{status_choices}>
requires_skills: <値またはnone>
requires_hooks: <値またはnone>
requires_install: <値またはnone>
dependencies: <値またはnone>
requires_env: <値またはnone>
requires_repo_tools: <値またはnone>
"""


CLASSIFICATION_PROMPT = _build_classification_prompt(
    STATUS_ENUM, _build_known_tools_note(load_repo_tools())
)


class SkillMetaFieldError(Exception):
    """Raised when aim output cannot be used to patch a skill."""


def parse_classification_response(response: str) -> dict[str, str]:
    """Parse the fixed ``field: value`` response from aim."""
    values: dict[str, str] = {}
    expected_fields = set(META_FIELDS)

    for line in response.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("```"):
            continue
        field, separator, value = stripped.partition(":")
        if not separator or field not in expected_fields:
            continue
        if field in values:
            raise SkillMetaFieldError(f"フィールド {field!r} が重複しています")

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1].strip()
        if not value:
            raise SkillMetaFieldError(f"フィールド {field!r} の値が空です")
        values[field] = value

    missing = [field for field in META_FIELDS if field not in values]
    if missing:
        raise SkillMetaFieldError(f"応答に不足しているフィールド: {', '.join(missing)}")
    return values


def _extract_response(entry: dict[str, object]) -> str:
    """Extract the successful response text from one aim JSON entry."""
    if not entry.get("success"):
        error = entry.get("error") or "不明なエラー"
        raise SkillMetaFieldError(f"aimが失敗しました: {error}")
    response = entry.get("response")
    if not isinstance(response, str) or not response.strip():
        raise SkillMetaFieldError("aimの応答が空です")
    return response


def _at_ref_for(skill_directory: Path) -> str:
    """Build a prompt ``@path`` token for ``skill_directory`` (repo-relative)."""
    rel = skill_directory.relative_to(REPO_ROOT).as_posix()
    if any(ch.isspace() for ch in rel):
        return f'@"{rel}"'
    return f"@{rel}"


def ask_skill_directory(skill_directory: Path) -> dict[str, object]:
    """Ask aim to classify one skill directory and return its JSON entry."""
    command = [
        AIM_COMMAND,
        "--prompt",
        f"{_at_ref_for(skill_directory)}\n{CLASSIFICATION_PROMPT}",
        "--format",
        "json",
        "--full-content-names",
        "SKILL.md,README.md",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise SkillMetaFieldError(f"aimコマンドが見つかりません。{AIM_INSTALL_HINT}") from exc
    except OSError as exc:
        raise SkillMetaFieldError(f"aimの起動に失敗しました: {exc}") from exc

    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        raise SkillMetaFieldError(
            f"aimが終了コード{result.returncode}で失敗しました: {details or '詳細なし'}"
        )

    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SkillMetaFieldError(f"aimのJSON出力を解釈できません: {exc}") from exc
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise SkillMetaFieldError("aimのJSON出力が1件の結果ではありません")
    return entries[0]


def _resolve_repo_path(raw_path: str) -> Path:
    path = Path(raw_path)
    resolved = (path if path.is_absolute() else REPO_ROOT / path).resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError(f"リポジトリ外のパスは指定できません: {raw_path}") from exc
    return resolved


def collect_skill_md_paths(raw_paths: Sequence[str]) -> tuple[list[Path], list[str]]:
    """Resolve optional SKILL.md/directory arguments into unique skill files."""
    if not raw_paths:
        return find_skill_md_files(REPO_ROOT), []

    paths: dict[Path, None] = {}
    errors: list[str] = []
    for raw_path in raw_paths:
        try:
            path = _resolve_repo_path(raw_path)
        except ValueError as exc:
            errors.append(str(exc))
            continue

        if path.is_dir():
            candidates = find_skill_md_files(path)
        elif path.is_file() and path.name == "SKILL.md":
            candidates = [path]
        elif not path.exists():
            errors.append(f"パスが存在しません: {raw_path}")
            continue
        else:
            errors.append(f"SKILL.mdまたはディレクトリを指定してください: {raw_path}")
            continue

        for candidate in candidates:
            paths[candidate.resolve()] = None

    return sorted(paths), errors


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SKILL.mdの新7 metaフィールドをaimで判定し、空欄だけを埋めます"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="対象のSKILL.mdまたはスキルディレクトリ（省略時はリポジトリ全体）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="AI呼び出しもファイル変更もせず、対象件数だけ確認します",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=6,
        help="同時に走らせる aim 呼び出し数（1〜10、既定6）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    skill_md_paths, collection_errors = collect_skill_md_paths(args.paths)
    for error in collection_errors:
        print(f"error: {error}", file=sys.stderr)
    if not skill_md_paths:
        print("対象のSKILL.mdがありません。", file=sys.stderr)
        return 1

    print(f"対象: {len(skill_md_paths)} SKILL.md")
    if args.dry_run:
        for path in skill_md_paths:
            print(f"would analyze {path.relative_to(REPO_ROOT)}")
        return 1 if collection_errors else 0

    if shutil.which(AIM_COMMAND) is None:
        print(
            f"error: aimコマンドが見つかりません。{AIM_INSTALL_HINT}",
            file=sys.stderr,
        )
        return 1
    if not os.environ.get("OPENROUTER_API_KEY"):
        print(
            "error: OPENROUTER_API_KEYが設定されていません。"
            "AI判定を実行する前に環境変数を設定してください。",
            file=sys.stderr,
        )
        return 1

    frontmatters: dict[Path, SkillFrontmatter] = {}
    for skill_md_path in skill_md_paths:
        rel_path = skill_md_path.relative_to(REPO_ROOT)
        frontmatter = read_frontmatter(skill_md_path)
        if frontmatter is None:
            print(f"warning: skipping {rel_path} (no valid frontmatter)", file=sys.stderr)
            continue
        frontmatters[skill_md_path] = frontmatter

    checked = len(frontmatters)
    updated = 0
    failures = 0
    done = 0

    print(
        f"querying {checked} skill directories via aim (jobs={args.jobs})...",
        flush=True,
    )

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        future_to_path = {
            executor.submit(ask_skill_directory, skill_md_path.parent): skill_md_path
            for skill_md_path in frontmatters
        }
        for future in as_completed(future_to_path):
            skill_md_path = future_to_path[future]
            frontmatter = frontmatters[skill_md_path]
            rel_path = skill_md_path.relative_to(REPO_ROOT)
            done += 1
            progress = f"[{done}/{checked}]"

            try:
                entry = future.result()
                values = parse_classification_response(_extract_response(entry))
            except SkillMetaFieldError as exc:
                failures += 1
                print(f"{progress} error: {rel_path}: {exc}", file=sys.stderr, flush=True)
                continue

            new_raw = frontmatter.raw
            changed_fields: list[str] = []
            for field in META_FIELDS:
                new_raw, changed = ensure_meta_field(new_raw, field, values[field])
                if changed:
                    changed_fields.append(field)

            if not changed_fields:
                print(f"{progress} unchanged {rel_path} (7 fields already populated)", flush=True)
                continue

            skill_md_path.write_text(frontmatter.with_raw(new_raw), encoding="utf-8")
            updated += 1
            print(f"{progress} updated {rel_path}: {', '.join(changed_fields)}", flush=True)

    print(f"Checked {checked} SKILL.md files, updated {updated}, failed {failures}.")
    return 1 if collection_errors or failures else 0


if __name__ == "__main__":
    sys.exit(main())
