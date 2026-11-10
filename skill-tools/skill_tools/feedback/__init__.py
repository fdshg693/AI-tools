"""Resolve a skill, tool, or workflow name and save one feedback file."""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..catalog import discover_catalog
from ..config import FB_DIR_ENV, SkillToolsConfig
from ..models import CatalogError, SkillToolsError, SourceError
from ..repo_tools.load import load_repo_tools
from ..source import CatalogSource
from ..workflows import list_workflow_ids

_SAFE_NAME = re.compile(r"[A-Za-z0-9._-]+")
_KIND_DIRS = {"skill": "skills", "tool": "tools", "workflow": "workflows"}


@dataclass(frozen=True)
class FbTarget:
    """One catalog entry that can receive feedback."""

    kind: str
    folder_name: str
    display_id: str


def resolve_fb_root(config: SkillToolsConfig) -> Path:
    """Environment override, then the configured path (already defaulted)."""

    override = os.environ.get(FB_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return config.fb.path


def resolve_fb_target(source: CatalogSource, name: str, kind: str | None) -> FbTarget:
    """Find exactly one catalog entry. Ambiguous or missing names are catalog errors."""

    kinds: Sequence[str] = (kind,) if kind else ("skill", "tool", "workflow")
    matches: list[FbTarget] = []
    failures: list[tuple[str, Exception]] = []
    for item in kinds:
        try:
            matches.extend(_matches(source, name, item))
        except (CatalogError, SourceError) as exc:
            if kind is not None:
                raise
            failures.append((item, exc))
    if len(matches) == 1:
        _ensure_safe_name(matches[0].folder_name)
        return matches[0]
    if not matches:
        raise _missing(name, kind, failures)
    raise _ambiguous(matches)


def save_feedback(
    root: Path,
    target: FbTarget,
    text: str,
    *,
    now: datetime | None = None,
) -> Path:
    """Create one feedback file exclusively and return its absolute path."""

    when = now if now is not None else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    stamp = when.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")
    directory = root / _KIND_DIRS[target.kind] / target.folder_name
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SkillToolsError(f"could not create feedback directory {directory}: {exc}") from exc
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    payload = text.encode("utf-8")
    index = 1
    while True:
        path = directory / (f"{stamp}-fb.md" if index == 1 else f"{stamp}-{index}-fb.md")
        try:
            fd = os.open(path, flags)
        except FileExistsError:
            index += 1
            continue
        except OSError as exc:
            raise SkillToolsError(f"could not create feedback file {path}: {exc}") from exc
        try:
            _write_all(fd, payload)
        except OSError as exc:
            os.close(fd)
            path.unlink(missing_ok=True)
            raise SkillToolsError(f"could not write feedback file {path}: {exc}") from exc
        os.close(fd)
        return path.resolve()


def _matches(source: CatalogSource, name: str, kind: str) -> list[FbTarget]:
    if kind == "skill":
        return [
            FbTarget("skill", record.name, record.canonical_id)
            for record in discover_catalog(source)
            if name in {record.name, record.canonical_id}
        ]
    if kind == "tool":
        return [
            FbTarget("tool", tool.key, tool.key)
            for tool in load_repo_tools(source)
            if name in {tool.key, tool.path.as_posix()}
        ]
    if kind == "workflow":
        return [
            FbTarget("workflow", workflow_id, workflow_id)
            for workflow_id in list_workflow_ids(source)
            if workflow_id == name
        ]
    raise CatalogError(f"unknown feedback kind: {kind}")


def _ensure_safe_name(name: str) -> None:
    if not _SAFE_NAME.fullmatch(name) or ".." in name:
        raise CatalogError(f"feedback target name is not a safe path component: {name!r}")


def _missing(name: str, kind: str | None, failures: list[tuple[str, Exception]]) -> CatalogError:
    subject = f"no {kind} named {name!r}" if kind else f"no feedback target named {name!r}"
    hint = (
        "Check names with `skill-tools list-skills`, `skill-tools list-tools`, "
        "or `skill-tools workflow list`."
    )
    if not failures:
        return CatalogError(f"{subject}. {hint}")
    detail = "; ".join(f"{label}: {exc}" for label, exc in failures)
    return CatalogError(f"{subject}. Some catalogs could not be read ({detail}). {hint}")


def _ambiguous(matches: list[FbTarget]) -> CatalogError:
    lines = ["feedback target is ambiguous; pass --fb-kind or a canonical ID:"]
    lines.extend(f"{match.kind}: {match.display_id}" for match in matches)
    return CatalogError("\n".join(lines))


def _write_all(fd: int, payload: bytes) -> None:
    view = payload
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("feedback write returned no progress")
        view = view[written:]
