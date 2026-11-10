"""ファイル/ディレクトリ本文の組み立て。"""

from __future__ import annotations

from pathlib import Path

from aim_files import format_inline_block, parse_full_content_names, read_text_or_error


def test_parse_full_content_names() -> None:
    assert parse_full_content_names(None) is None
    assert parse_full_content_names("SKILL.md, README.md") == {"SKILL.md", "README.md"}
    assert parse_full_content_names("") == set()


def test_read_file(tmp_path: Path) -> None:
    path = tmp_path / "foo.py"
    path.write_text("hello", encoding="utf-8")
    text, error = read_text_or_error(path)
    assert error is None
    assert text == "hello"


def test_missing_path(tmp_path: Path) -> None:
    text, error = read_text_or_error(tmp_path / "nope.py")
    assert text is None
    assert error is not None
    assert "存在しません" in error


def test_binary_file(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"\x00\x01\x02")
    text, error = read_text_or_error(path)
    assert text is None
    assert error is not None
    assert "バイナリ" in error


def test_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "x.txt"
    path.write_bytes(b"\xff\xfe")
    text, error = read_text_or_error(path)
    assert text is None
    assert error is not None
    assert "UTF-8" in error


def test_directory_tree_and_contents(tmp_path: Path) -> None:
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text("skill-body", encoding="utf-8")
    nested = root / "sub"
    nested.mkdir()
    (nested / "note.txt").write_text("note-body", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("secret", encoding="utf-8")

    text, error = read_text_or_error(root)
    assert error is None
    assert text is not None
    assert "ディレクトリツリー:" in text
    assert "SKILL.md" in text
    assert "note.txt" in text
    assert "skill-body" in text
    assert "note-body" in text
    assert ".git" not in text
    assert "secret" not in text
    assert "--- FILE: SKILL.md ---" in text
    assert "--- FILE: sub/note.txt ---" in text


def test_full_content_names_omits_other_files(tmp_path: Path) -> None:
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text("skill-body", encoding="utf-8")
    (root / "other.py").write_text("other-body", encoding="utf-8")

    text, error = read_text_or_error(root, {"SKILL.md"})
    assert error is None
    assert text is not None
    assert "skill-body" in text
    assert "--- FILE: SKILL.md ---" in text
    assert "other-body" not in text
    assert "--- FILE: other.py ---" not in text
    assert "内容省略（対象外ファイル）" in text


def test_binary_in_directory_is_skipped_in_tree(tmp_path: Path) -> None:
    root = tmp_path / "d"
    root.mkdir()
    (root / "ok.txt").write_text("ok", encoding="utf-8")
    (root / "x.bin").write_bytes(b"\x00\x01")
    text, error = read_text_or_error(root)
    assert error is None
    assert text is not None
    assert "ok" in text
    assert "読み込みスキップ" in text
    assert "--- FILE: x.bin ---" not in text


def test_format_inline_block_file_and_dir(tmp_path: Path) -> None:
    file_path = tmp_path / "a.py"
    file_path.write_text("x", encoding="utf-8")
    dir_path = tmp_path / "d"
    dir_path.mkdir()
    assert format_inline_block("a.py", file_path, "x").startswith("--- FILE: a.py ---")
    assert format_inline_block("d", dir_path, "tree").startswith("--- DIR: d ---")
