from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import PurePosixPath

DIR_INDEX_NAMES = ("README.md", "AGENTS.md", "index.md")
EXACT = "exact"
UNIQUE_BASENAME = "unique-basename"
UNIQUE_SUFFIX = "unique-suffix"
GIT_RENAME = "git-rename"
UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ResolvedLink:
    resolved: str | None
    confidence: str
    anchor: str | None


def resolve_link(raw: str, source_path: str, files: Collection[str]) -> ResolvedLink:
    path_part, anchor = _split_target(raw)
    if not path_part:
        return ResolvedLink(resolved=None, confidence=UNRESOLVED, anchor=anchor)

    file_set = set(files)
    source_dir = _parent(source_path)

    hit = _lookup_cascade(path_part, source_dir, file_set)
    if hit is not None:
        return ResolvedLink(resolved=hit, confidence=EXACT, anchor=anchor)

    if not PurePosixPath(path_part).suffix:
        hit = _lookup_cascade(f"{path_part}.md", source_dir, file_set)
        if hit is not None:
            return ResolvedLink(resolved=hit, confidence=EXACT, anchor=anchor)

    basename = PurePosixPath(path_part).name
    base_hits = [path for path in file_set if PurePosixPath(path).name == basename]
    if len(base_hits) == 1:
        return ResolvedLink(resolved=base_hits[0], confidence=UNIQUE_BASENAME, anchor=anchor)

    suffix = _suffix(path_part)
    if "/" in suffix:
        suffix_hits = [path for path in file_set if path == suffix or path.endswith(f"/{suffix}")]
        if len(suffix_hits) == 1:
            return ResolvedLink(resolved=suffix_hits[0], confidence=UNIQUE_SUFFIX, anchor=anchor)

    return ResolvedLink(resolved=None, confidence=UNRESOLVED, anchor=anchor)


def _lookup_cascade(path_part: str, source_dir: str, files: set[str]) -> str | None:
    source_candidate = _join(source_dir, path_part)
    if source_candidate is not None:
        hit = _lookup_exact(source_candidate, files)
        if hit is not None:
            return hit

    root_candidate = _join("", path_part)
    if root_candidate is not None:
        hit = _lookup_exact(root_candidate, files)
        if hit is not None:
            return hit

    if source_candidate is not None:
        hit = _lookup_ci(source_candidate, files)
        if hit is not None:
            return hit
    if root_candidate is not None and root_candidate != source_candidate:
        hit = _lookup_ci(root_candidate, files)
        if hit is not None:
            return hit
    return None


def _lookup_exact(candidate: str, files: set[str]) -> str | None:
    if candidate in files:
        return candidate
    return _dir_index(candidate, files, case_sensitive=True)


def _lookup_ci(candidate: str, files: set[str]) -> str | None:
    lowered = candidate.lower()
    hits = [path for path in files if path.lower() == lowered]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        return None
    return _dir_index(candidate, files, case_sensitive=False)


def _dir_index(candidate: str, files: set[str], *, case_sensitive: bool) -> str | None:
    for name in DIR_INDEX_NAMES:
        target = f"{candidate}/{name}" if candidate else name
        if case_sensitive:
            if target in files:
                return target
            continue
        lowered = target.lower()
        hits = [path for path in files if path.lower() == lowered]
        if len(hits) == 1:
            return hits[0]
    return None


def _split_target(raw: str) -> tuple[str, str | None]:
    dest = raw.strip()
    if dest.startswith("@"):
        dest = dest[1:]
    dest = dest.replace("\\", "/")
    if dest.startswith("#"):
        return "", dest[1:] or None
    if "#" in dest:
        path, anchor = dest.split("#", 1)
        return path, anchor
    return dest, None


def lookup_candidates(raw: str, files: Collection[str]) -> list[str]:
    path_part, _anchor = _split_target(raw)
    if not path_part:
        return []
    basename = PurePosixPath(path_part).name
    base_hits = sorted(path for path in files if PurePosixPath(path).name == basename)
    if len(base_hits) > 1:
        return base_hits
    suffix = _suffix(path_part)
    if "/" in suffix:
        suffix_hits = sorted(
            path for path in files if path == suffix or path.endswith(f"/{suffix}")
        )
        if len(suffix_hits) > 1:
            return suffix_hits
    return base_hits if len(base_hits) > 1 else []


def fallback_candidates(raw: str, files: Collection[str]) -> list[str]:
    """Ambiguous suffix hits first, then ambiguous basenames. Empty if unique or none."""
    path_part, _anchor = _split_target(raw)
    if not path_part:
        return []
    suffix = _suffix(path_part)
    if "/" in suffix:
        suffix_hits = sorted(
            path for path in files if path == suffix or path.endswith(f"/{suffix}")
        )
        if len(suffix_hits) > 1:
            return suffix_hits
    basename = PurePosixPath(path_part).name
    base_hits = sorted(path for path in files if PurePosixPath(path).name == basename)
    if len(base_hits) > 1:
        return base_hits
    return []


def _parent(path: str) -> str:
    normalized = path.replace("\\", "/")
    if "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0]


def _join(base_dir: str, rel: str) -> str | None:
    parts: list[str] = []
    if base_dir:
        parts.extend(part for part in base_dir.split("/") if part not in ("", "."))
    rel = rel.replace("\\", "/")
    if rel.startswith("/"):
        parts = []
        rel = rel.lstrip("/")
    for part in rel.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _suffix(path_part: str) -> str:
    parts: list[str] = []
    for part in path_part.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            parts.clear()
            continue
        parts.append(part)
    return "/".join(parts)
