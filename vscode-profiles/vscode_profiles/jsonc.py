from __future__ import annotations

import json

from vscode_profiles.errors import CliError


def loads(text: str) -> object:
    if text.startswith("\ufeff"):
        text = text[1:]
    try:
        return json.loads(_strip_jsonc(text))
    except json.JSONDecodeError as exc:
        raise CliError(f"invalid JSON: {exc}") from exc


def _strip_jsonc(text: str) -> str:
    return _strip_trailing_commas(_strip_comments(text))


def _strip_comments(text: str) -> str:
    out: list[str] = []
    i = 0
    length = len(text)
    in_string = False
    escape = False
    while i < length:
        char = text[i]
        if in_string:
            out.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue
        if char == "/" and i + 1 < length and text[i + 1] == "/":
            i += 2
            while i < length and text[i] not in "\r\n":
                i += 1
            continue
        if char == "/" and i + 1 < length and text[i + 1] == "*":
            i += 2
            while i + 1 < length and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            if i + 1 >= length:
                raise CliError("unterminated block comment")
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    out: list[str] = []
    i = 0
    length = len(text)
    in_string = False
    escape = False
    while i < length:
        char = text[i]
        if in_string:
            out.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue
        if char == ",":
            j = i + 1
            while j < length and text[j] in " \t\r\n":
                j += 1
            if j < length and text[j] in "}]":
                i += 1
                continue
        out.append(char)
        i += 1
    return "".join(out)
