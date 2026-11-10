"""プロンプト本文から ``@path`` を検出し、CWD 基準で解決する。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class AtError(Exception):
    """``@path`` の検出・解決に失敗した場合。"""


@dataclass(frozen=True)
class AtRef:
    """プロンプト中の1つの ``@path``。"""

    start: int
    end: int
    raw_path: str
    resolved: Path


def resolve_path(raw_path: str, cwd: Path) -> Path:
    """相対パスは ``cwd`` 基準で解決し、``~`` を展開して絶対パスを返す。"""
    p = Path(raw_path).expanduser()
    return (p if p.is_absolute() else cwd / p).resolve()


def strip_at_refs(text: str, refs: Sequence[AtRef]) -> str:
    """``@path`` トークンを除いた残り（指示文）を返す。"""
    out = text
    for ref in reversed(refs):
        out = out[: ref.start] + out[ref.end :]
    return out.strip()


def expand_at_refs(text: str, replacements: Sequence[tuple[AtRef, str]]) -> str:
    """各 ``@path`` を対応する本文ブロックへ置換する。"""
    out = text
    for ref, block in reversed(replacements):
        out = out[: ref.start] + block + out[ref.end :]
    return out


def find_at_refs(text: str, cwd: Path) -> list[AtRef]:
    """トークン先頭の ``@path`` を左から検出する。言及やメールアドレスは残す。"""
    refs: list[AtRef] = []
    i = 0
    while i < len(text):
        if text[i] == "@" and (i == 0 or text[i - 1].isspace()):
            ref, consumed = _parse_at(text, i, cwd)
            if ref is not None:
                refs.append(ref)
                i = ref.end
                continue
            i += consumed
            continue
        i += 1
    return refs


def is_explicit_path_token(token: str) -> bool:
    """未クオートでパスと断定できるトークンか（無ければエラーにする対象）。"""
    if "/" in token or "\\" in token:
        return True
    if token.startswith(("./", ".\\", "../", "..\\", "~/", "~\\")):
        return True
    return _is_drive_prefix(token)


def _parse_at(text: str, at_index: int, cwd: Path) -> tuple[AtRef | None, int]:
    """``@`` 位置から1件読む。展開しない場合は ``(None, 1)``（``@`` だけ進める）。"""
    j = at_index + 1
    if j >= len(text):
        return None, 1

    if text[j] in "\"'":
        ref = _parse_quoted(text, at_index, j, cwd)
        return ref, ref.end - at_index

    k = j
    while k < len(text) and not text[k].isspace():
        k += 1
    token = text[j:k]
    if not token:
        return None, 1

    matched = _longest_existing_prefix(token, cwd)
    if matched is not None:
        return (
            AtRef(
                start=at_index,
                end=j + len(matched),
                raw_path=matched,
                resolved=resolve_path(matched, cwd),
            ),
            len(matched) + 1,
        )
    if is_explicit_path_token(token):
        raise AtError(f"パスが存在しません: {token}")
    return None, 1


def _parse_quoted(text: str, at_index: int, quote_index: int, cwd: Path) -> AtRef:
    quote = text[quote_index]
    k = quote_index + 1
    while k < len(text) and text[k] != quote:
        k += 1
    if k >= len(text):
        raise AtError("引用符が閉じられていません")
    raw_path = text[quote_index + 1 : k]
    if not raw_path:
        raise AtError("空のパスです")
    resolved = resolve_path(raw_path, cwd)
    if not resolved.exists():
        raise AtError(f"パスが存在しません: {raw_path}")
    return AtRef(start=at_index, end=k + 1, raw_path=raw_path, resolved=resolved)


def _longest_existing_prefix(token: str, cwd: Path) -> str | None:
    best: str | None = None
    for i in range(1, len(token) + 1):
        prefix = token[:i]
        if _skip_prefix(prefix):
            continue
        if not resolve_path(prefix, cwd).exists():
            continue
        if not _is_valid_cut(prefix, token):
            continue
        best = prefix
    return best


def _skip_prefix(prefix: str) -> bool:
    """``.`` / ``..`` / ``~`` / ``C:`` 単体は常に存在するので最長一致から除外する。"""
    if prefix in (".", "..", "~"):
        return True
    return _is_drive_only(prefix)


def _is_drive_only(prefix: str) -> bool:
    return len(prefix) == 2 and prefix[0].isalpha() and prefix[1] == ":"


def _is_drive_prefix(token: str) -> bool:
    if len(token) < 2 or not token[0].isalpha() or token[1] != ":":
        return False
    return len(token) == 2 or token[2] in "/\\"


def _is_valid_cut(prefix: str, token: str) -> bool:
    """次文字が ASCII ファイル名の続きなら、そこで切らない。

    ``str.isalnum()`` は助詞の「を」等にも真を返すため使わない。
    ``@foo.py`` を ``foo`` ディレクトリへ誤展開しない、かつ
    ``@src/foo.pyを要約して`` は ``src/foo.py`` で切れるようにする。
    """
    if prefix == token:
        return True
    nxt = token[len(prefix)]
    if nxt in "/\\":
        return False
    return not (nxt.isascii() and (nxt.isalnum() or nxt in "._+-"))
