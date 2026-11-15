"""ファイル/ディレクトリ本文の組み立て。"""

from __future__ import annotations

import os
from pathlib import Path

BINARY_SNIFF_SIZE = 8192
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
}


def parse_full_content_names(raw: str | None) -> set[str] | None:
    """``--full-content-names`` のカンマ区切りを集合にする。未指定は None。"""
    if raw is None:
        return None
    return {name.strip() for name in raw.split(",") if name.strip()}


def format_inline_block(raw_path: str, resolved: Path, content: str) -> str:
    """単発経路で ``@path`` の位置に埋め込む本文ブロック。"""
    kind = "DIR" if resolved.is_dir() else "FILE"
    return f"--- {kind}: {raw_path} ---\n{content}"


def read_text_or_error(
    path: Path, full_content_names: set[str] | None = None
) -> tuple[str | None, str | None]:
    """戻り値は ``(ファイル内容, None)`` または ``(None, エラーメッセージ)``。

    ``full_content_names`` はディレクトリ入力時のみ使う。指定した場合、
    ディレクトリ配下のうちファイル名がこの集合に含まれるものだけ内容を含め、
    それ以外はツリー listing 上のパスのみになる（内容は渡さない）。
    """
    if not path.exists():
        return None, f"パスが存在しません: {path}"
    if path.is_dir():
        return _format_directory_text(path, full_content_names), None

    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"ファイルの読み込みに失敗しました: {exc}"

    if b"\x00" in raw[:BINARY_SNIFF_SIZE]:
        return None, "バイナリファイルのため対象外です。"

    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "UTF-8としてデコードできませんでした。"


def _collect_directory_entries(path: Path) -> tuple[list[tuple[Path, bool]], list[Path]]:
    """除外ディレクトリを省いて、ツリー表示用のパスとファイル一覧を集める。"""
    entries: list[tuple[Path, bool]] = []
    files: list[Path] = []

    for root, directory_names, file_names in os.walk(path, topdown=True):
        directory_names[:] = sorted(
            name for name in directory_names if name not in EXCLUDED_DIRECTORY_NAMES
        )
        for name in directory_names:
            entries.append((Path(root) / name, True))
        for name in sorted(file_names):
            file_path = Path(root) / name
            entries.append((file_path, False))
            files.append(file_path)

    return entries, files


def _format_directory_text(path: Path, full_content_names: set[str] | None = None) -> str:
    """ディレクトリのツリー listing と各ファイル内容を1つの文字列にする。

    ``full_content_names`` を指定した場合、ファイル名がこの集合に含まれるものだけ
    内容を含め、それ以外はツリー listing 上のパスのみ（内容なし）にする。
    """
    entries, files = _collect_directory_entries(path)
    file_contents: dict[tuple[str, ...], str] = {}
    file_errors: dict[tuple[str, ...], str] = {}
    file_filtered: set[tuple[str, ...]] = set()
    tree_children: dict[tuple[str, ...], list[tuple[str, bool]]] = {(): []}

    for entry_path, is_directory in entries:
        relative_parts = entry_path.relative_to(path).parts
        parent_parts = relative_parts[:-1]
        tree_children.setdefault(parent_parts, []).append((relative_parts[-1], is_directory))
        if is_directory:
            tree_children.setdefault(relative_parts, [])

    for file_path in files:
        relative_parts = file_path.relative_to(path).parts
        if full_content_names is not None and file_path.name not in full_content_names:
            file_filtered.add(relative_parts)
            continue
        content, error = read_text_or_error(file_path)
        if content is not None:
            file_contents[relative_parts] = content
        else:
            file_errors[relative_parts] = error or "読み込めませんでした。"

    def render_tree(parent_parts: tuple[str, ...], prefix: str) -> list[str]:
        children = sorted(
            tree_children.get(parent_parts, []), key=lambda item: (not item[1], item[0])
        )
        lines: list[str] = []
        for index, (name, is_directory) in enumerate(children):
            is_last = index == len(children) - 1
            connector = "└──" if is_last else "├──"
            child_parts = parent_parts + (name,)
            note = ""
            if not is_directory and child_parts in file_errors:
                note = f" [読み込みスキップ: {file_errors[child_parts]}]"
            elif not is_directory and child_parts in file_filtered:
                note = " [内容省略（対象外ファイル）]"
            lines.append(f"{prefix}{connector} {name}{note}")
            if is_directory:
                child_prefix = prefix + ("    " if is_last else "│   ")
                lines.extend(render_tree(child_parts, child_prefix))
        return lines

    sections = ["ディレクトリツリー:", ".", *render_tree((), "")]
    for relative_parts, content in sorted(file_contents.items()):
        relative_path = "/".join(relative_parts)
        sections.extend([f"\n--- FILE: {relative_path} ---", content])
    return "\n".join(sections)
