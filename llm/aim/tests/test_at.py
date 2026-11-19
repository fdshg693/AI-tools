"""プロンプト中の ``@path`` 検出・解決。"""

from __future__ import annotations

from pathlib import Path

import pytest

from aim_at import (
    AtError,
    expand_at_refs,
    find_at_refs,
    is_explicit_path_token,
    strip_at_refs,
)


def test_is_explicit_path_token() -> None:
    assert is_explicit_path_token("src/foo.py")
    assert is_explicit_path_token("src\\foo.py")
    assert is_explicit_path_token("./a.py")
    assert is_explicit_path_token("../a.py")
    assert is_explicit_path_token("~/a.py")
    assert is_explicit_path_token("C:\\a.py")
    assert is_explicit_path_token("C:/a.py")
    assert not is_explicit_path_token("foo.py")
    assert not is_explicit_path_token("user")
    assert not is_explicit_path_token("SKILL.md")


def test_finds_existing_file(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text("x", encoding="utf-8")
    refs = find_at_refs("@foo.py を要約して", tmp_path)
    assert len(refs) == 1
    assert refs[0].raw_path == "foo.py"
    assert refs[0].start == 0
    assert refs[0].resolved == (tmp_path / "foo.py").resolve()


def test_particle_after_path_without_space(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text("x", encoding="utf-8")
    text = "@src/foo.pyを要約して"
    refs = find_at_refs(text, tmp_path)
    assert len(refs) == 1
    assert refs[0].raw_path == "src/foo.py"
    assert text[refs[0].end :] == "を要約して"


def test_email_is_not_a_path(tmp_path: Path) -> None:
    assert find_at_refs("contact foo@gmail.com please", tmp_path) == []


def test_mention_without_file_is_left(tmp_path: Path) -> None:
    assert find_at_refs("hey @user hello", tmp_path) == []


def test_missing_bare_name_is_left(tmp_path: Path) -> None:
    assert find_at_refs("@foo.py を見て", tmp_path) == []


def test_dir_named_foo_does_not_steal_foo_py(tmp_path: Path) -> None:
    (tmp_path / "foo").mkdir()
    assert find_at_refs("@foo.py です", tmp_path) == []


def test_prefers_foo_py_over_foo_dir_when_both_exist(tmp_path: Path) -> None:
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo.py").write_text("x", encoding="utf-8")
    refs = find_at_refs("@foo.py", tmp_path)
    assert refs[0].raw_path == "foo.py"
    assert refs[0].resolved.is_file()


def test_gitignore_is_not_cut_at_dot(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*", encoding="utf-8")
    refs = find_at_refs("@.gitignore", tmp_path)
    assert refs[0].raw_path == ".gitignore"


def test_quoted_path_with_spaces(tmp_path: Path) -> None:
    (tmp_path / "my file.txt").write_text("hi", encoding="utf-8")
    text = '@"my file.txt"を読んで'
    refs = find_at_refs(text, tmp_path)
    assert refs[0].raw_path == "my file.txt"
    assert text[refs[0].end :] == "を読んで"


def test_quoted_missing_is_error(tmp_path: Path) -> None:
    with pytest.raises(AtError, match="存在しません"):
        find_at_refs('@"no such.txt"', tmp_path)


def test_unterminated_quote_is_error(tmp_path: Path) -> None:
    with pytest.raises(AtError, match="引用符"):
        find_at_refs('@"oops', tmp_path)


def test_empty_quoted_path_is_error(tmp_path: Path) -> None:
    with pytest.raises(AtError, match="空のパス"):
        find_at_refs('@""', tmp_path)


def test_missing_explicit_path_is_error(tmp_path: Path) -> None:
    with pytest.raises(AtError, match="存在しません"):
        find_at_refs("@src/missing.py を", tmp_path)


def test_missing_dot_slash_is_error(tmp_path: Path) -> None:
    with pytest.raises(AtError, match="存在しません"):
        find_at_refs("@./nope.py", tmp_path)


def test_dot_slash_existing(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    refs = find_at_refs("@./a.py", tmp_path)
    assert refs[0].raw_path == "./a.py"


def test_multiple_refs_and_strip(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / "b.py").write_text("b", encoding="utf-8")
    text = "@a.py @b.py を要約"
    refs = find_at_refs(text, tmp_path)
    assert [ref.raw_path for ref in refs] == ["a.py", "b.py"]
    assert strip_at_refs(text, refs) == "を要約"


def test_expand_at_refs_replaces_in_place(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    text = "前 @a.py 後"
    refs = find_at_refs(text, tmp_path)
    out = expand_at_refs(text, [(refs[0], "BLOCK")])
    assert out == "前 BLOCK 後"


def test_adjacent_at_without_space_only_first(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / "b.py").write_text("b", encoding="utf-8")
    refs = find_at_refs("@a.py@b.py", tmp_path)
    assert [ref.raw_path for ref in refs] == ["a.py"]
