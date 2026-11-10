"""Text-level patcher for scalar fields inside a SKILL.md frontmatter's meta: block.

Edits the raw frontmatter text directly (rather than yaml.dump-ing the parsed
dict) so unrelated formatting and comments are left untouched. Shared by
skill_meta_version.py, skill_meta_description.py, and bump_skill_versions.py,
which are thin, field-specific wrappers around this generic patcher.
"""

from __future__ import annotations

import re

import yaml

_META_LINE_RE = re.compile(r"^meta:\s*(#.*)?$")
_INDENTED_RE = re.compile(r"^([ \t]+)\S")


def _format_scalar(value: str) -> str:
    """Render ``value`` as a YAML-safe plain-line scalar, quoting only if needed.

    Values classified by AI (e.g. ``requires_install``) can start with reserved
    YAML indicators like ``@`` (npm scoped packages) or contain ``: ``, which
    would otherwise corrupt the frontmatter as an unquoted plain scalar.
    """
    dumped = yaml.safe_dump(value, default_flow_style=True).strip()
    if dumped.endswith("\n..."):
        dumped = dumped[: -len("\n...")]
    return dumped


def has_meta_field(data: dict, field: str) -> bool:
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return False
    value = meta.get(field)
    return bool(str(value).strip()) if value is not None else False


def _locate_field(lines: list[str], field: str) -> tuple[int | None, int, str, str]:
    """Find ``field:`` inside the ``meta:`` block.

    Returns ``(field_line_idx_or_None, meta_line_idx_or_-1, indent, current_value)``.
    ``field_line_idx`` is ``None`` when the block exists but the field is absent.
    """
    field_line_re = re.compile(rf"^(?P<indent>[ \t]+){re.escape(field)}:\s*(?P<value>.*)$")
    meta_idx = next((i for i, line in enumerate(lines) if _META_LINE_RE.match(line)), None)
    if meta_idx is None:
        return None, -1, "  ", ""

    block_end = len(lines)
    indent = "  "
    for i in range(meta_idx + 1, len(lines)):
        line = lines[i]
        if line.strip() == "":
            continue
        indented_match = _INDENTED_RE.match(line)
        if not indented_match:
            block_end = i
            break
        indent = indented_match.group(1)

    for i in range(meta_idx + 1, block_end):
        match = field_line_re.match(lines[i])
        if match:
            value = match.group("value").split("#", 1)[0].strip().strip("'\"")
            return i, meta_idx, match.group("indent"), value

    return None, meta_idx, indent, ""


def ensure_meta_field(raw: str, field: str, default_value: str) -> tuple[str, bool]:
    """Return (patched_raw, changed) with a non-empty meta.<field> guaranteed.

    Leaves an already non-empty value untouched.
    """
    return ensure_meta_field_literal(raw, field, _format_scalar(default_value))


def set_meta_field(raw: str, field: str, new_value: str) -> tuple[str, bool]:
    """Return (patched_raw, changed) with meta.<field> forced to ``new_value``.

    Unlike ``ensure_meta_field``, overwrites an existing non-empty value.
    """
    lines = raw.split("\n")
    field_idx, meta_idx, indent, current_value = _locate_field(lines, field)

    if meta_idx == -1:
        return _append_meta_block(lines, field, _format_scalar(new_value)), True
    if field_idx is not None:
        if current_value == new_value:
            return raw, False
        lines[field_idx] = f"{indent}{field}: {_format_scalar(new_value)}"
        return "\n".join(lines), True

    lines.insert(meta_idx + 1, f"{indent}{field}: {_format_scalar(new_value)}")
    return "\n".join(lines), True


def ensure_meta_field_literal(raw: str, field: str, default_literal: str) -> tuple[str, bool]:
    """Like ``ensure_meta_field``, but writes ``default_literal`` verbatim as
    YAML source instead of running it through ``_format_scalar``'s string-scalar
    quoting.

    For array-typed fields (e.g. ``tag``) whose default is flow-sequence
    syntax like ``"[]"``, which ``_format_scalar`` (built for plain string
    values) would otherwise quote as the literal string ``"'[]'"``.
    """
    lines = raw.split("\n")
    field_idx, meta_idx, indent, current_value = _locate_field(lines, field)

    if meta_idx == -1:
        return _append_meta_block(lines, field, default_literal), True
    if field_idx is not None:
        if current_value:
            return raw, False
        lines[field_idx] = f"{indent}{field}: {default_literal}"
        return "\n".join(lines), True

    lines.insert(meta_idx + 1, f"{indent}{field}: {default_literal}")
    return "\n".join(lines), True


def _append_meta_block(lines: list[str], field: str, formatted_value: str) -> str:
    new_lines = list(lines)
    while new_lines and new_lines[-1] == "":
        new_lines.pop()
    new_lines.append("meta:")
    new_lines.append(f"  {field}: {formatted_value}")
    return "\n".join(new_lines)
