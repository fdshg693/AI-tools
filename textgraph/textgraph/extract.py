from __future__ import annotations

import re
from dataclasses import dataclass

_INLINE = re.compile(
    r"(?P<img>!)?\[(?:[^\]]*)\]\(\s*(?P<dest><[^>]+>|[^)\s]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)
_REF = re.compile(
    r"^[ \t]{0,3}\[[^\]]+\]:[ \t]+(?P<dest><[^>]+>|\S+)",
    re.MULTILINE,
)
_WIKI = re.compile(r"\[\[(?P<dest>[^\]|]+)(?:\|[^\]]*)?\]\]")
_AT = re.compile(r"@(?P<dest>\.\./|\./)(?P<rest>[^\s]+)")

_REMOTE_PREFIXES = (
    "http://",
    "https://",
    "mailto:",
    "data:",
    "javascript:",
    "ftp://",
)


@dataclass(frozen=True)
class ExtractedLink:
    raw: str
    kind: str
    line: int


def extract_links(text: str) -> list[ExtractedLink]:
    masked = _mask_code(text)
    occupied: list[tuple[int, int]] = []
    found: list[tuple[int, ExtractedLink]] = []

    for match in _INLINE.finditer(masked):
        dest = _clean_dest(match.group("dest"))
        if dest is None:
            continue
        kind = "image" if match.group("img") else "markdown"
        occupied.append(match.span())
        found.append(
            (match.start(), ExtractedLink(raw=dest, kind=kind, line=_line_at(text, match.start())))
        )

    for match in _REF.finditer(masked):
        dest = _clean_dest(match.group("dest"))
        if dest is None:
            continue
        occupied.append(match.span())
        found.append(
            (match.start(), ExtractedLink(raw=dest, kind="ref", line=_line_at(text, match.start())))
        )

    for match in _WIKI.finditer(masked):
        dest = _clean_dest(match.group("dest"))
        if dest is None:
            continue
        occupied.append(match.span())
        found.append(
            (
                match.start(),
                ExtractedLink(raw=dest, kind="wiki", line=_line_at(text, match.start())),
            )
        )

    for match in _AT.finditer(masked):
        if _overlaps(match.span(), occupied):
            continue
        dest = match.group("dest") + match.group("rest")
        if _clean_dest(dest) is None:
            continue
        found.append(
            (match.start(), ExtractedLink(raw=dest, kind="at", line=_line_at(text, match.start())))
        )

    found.sort(key=lambda item: item[0])
    return [link for _, link in found]


def _line_at(text: str, offset: int) -> int:
    return text[:offset].count("\n") + 1


def _clean_dest(dest: str) -> str | None:
    dest = dest.strip()
    if dest.startswith("<") and dest.endswith(">") and len(dest) >= 2:
        dest = dest[1:-1].strip()
    path, _anchor = _split_anchor(dest)
    if not path:
        return None
    lowered = path.lower()
    if lowered.startswith(_REMOTE_PREFIXES):
        return None
    return dest


def _split_anchor(raw: str) -> tuple[str, str | None]:
    if raw.startswith("#"):
        return "", raw[1:] or None
    if "#" in raw:
        path, anchor = raw.split("#", 1)
        return path, anchor
    return raw, None


def _overlaps(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
    start, end = span
    for other_start, other_end in occupied:
        if start < other_end and end > other_start:
            return True
    return False


def _fence_at(text: str, index: int) -> bool:
    pos = index
    spaces = 0
    while pos < len(text) and text[pos] == " " and spaces < 3:
        pos += 1
        spaces += 1
    return text.startswith("```", pos)


def _mask_until_newline(chars: list[str], text: str, index: int) -> int:
    pos = index
    while pos < len(text) and text[pos] != "\n":
        chars[pos] = " "
        pos += 1
    if pos < len(text) and text[pos] == "\n":
        return pos + 1
    return pos


def _mask_code(text: str) -> str:
    chars = list(text)
    n = len(text)
    i = 0
    line_start = True
    in_fence = False
    while i < n:
        if in_fence:
            if line_start and _fence_at(text, i):
                in_fence = False
                i = _mask_until_newline(chars, text, i)
                line_start = True
                continue
            if text[i] == "\n":
                line_start = True
                i += 1
                continue
            chars[i] = " "
            i += 1
            line_start = False
            continue
        if line_start and _fence_at(text, i):
            in_fence = True
            i = _mask_until_newline(chars, text, i)
            line_start = True
            continue
        if text[i] == "`":
            close = text.find("`", i + 1)
            if close == -1:
                i += 1
                line_start = False
                continue
            for pos in range(i, close + 1):
                if chars[pos] != "\n":
                    chars[pos] = " "
            i = close + 1
            line_start = False
            continue
        if text[i] == "\n":
            line_start = True
        else:
            line_start = False
        i += 1
    return "".join(chars)
