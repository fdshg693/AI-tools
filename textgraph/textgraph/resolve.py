from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

DIR_INDEX_NAMES = ("README.md", "AGENTS.md", "index.md")
EXACT = "exact"
UNIQUE_BASENAME = "unique-basename"
UNIQUE_SUFFIX = "unique-suffix"
GIT_RENAME = "git-rename"
GIT_RENAME_BASENAME = "git-rename-basename"
UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ResolvedLink:
    resolved: str | None
    confidence: str
    anchor: str | None


class FileIndex:
    """A file set with lookup tables built once and reused across links.

    Resolving thousands of broken links against the same file set would
    otherwise rescan every path (basename, lower-case) per link. Each table is
    built on first use, so exact-only resolution stays as cheap as a set.
    """

    def __init__(self, files: Collection[str]) -> None:
        self.files: frozenset[str] = frozenset(files)
        self._by_name: dict[str, list[str]] | None = None
        self._by_lower: dict[str, list[str]] | None = None
        self._dirs: frozenset[str] | None = None

    def __contains__(self, path: object) -> bool:
        return path in self.files

    def __iter__(self) -> Iterator[str]:
        return iter(self.files)

    def __len__(self) -> int:
        return len(self.files)

    @property
    def dirs(self) -> frozenset[str]:
        if self._dirs is None:
            self._dirs = directories_of(self.files)
        return self._dirs

    def with_name(self, basename: str) -> list[str]:
        if self._by_name is None:
            by_name: dict[str, list[str]] = {}
            for path in self.files:
                by_name.setdefault(_basename(path), []).append(path)
            self._by_name = by_name
        return self._by_name.get(basename, [])

    def with_suffix(self, suffix: str) -> list[str]:
        """Paths equal to ``suffix`` or ending in ``/suffix``."""
        return [
            path
            for path in self.with_name(_basename(suffix))
            if path == suffix or path.endswith(f"/{suffix}")
        ]

    def casefold_hits(self, candidate: str) -> list[str]:
        if self._by_lower is None:
            by_lower: dict[str, list[str]] = {}
            for path in self.files:
                by_lower.setdefault(path.lower(), []).append(path)
            self._by_lower = by_lower
        return self._by_lower.get(candidate.lower(), [])


def as_file_index(files: Collection[str]) -> FileIndex:
    return files if isinstance(files, FileIndex) else FileIndex(files)


def resolve_link(raw: str, source_path: str, files: Collection[str]) -> ResolvedLink:
    """Resolve ``raw`` written in ``source_path``.

    ``files`` may be any collection of POSIX paths; pass a :class:`FileIndex`
    to reuse its lookup tables across many calls.
    """
    path_part, anchor = _split_target(raw)
    if not path_part:
        return ResolvedLink(resolved=None, confidence=UNRESOLVED, anchor=anchor)

    index = as_file_index(files)
    source_dir = _parent(source_path)

    hit = _lookup_cascade(path_part, source_dir, index)
    if hit is not None:
        return ResolvedLink(resolved=hit, confidence=EXACT, anchor=anchor)

    if not PurePosixPath(path_part).suffix:
        hit = _lookup_cascade(f"{path_part}.md", source_dir, index)
        if hit is not None:
            return ResolvedLink(resolved=hit, confidence=EXACT, anchor=anchor)

    base_hits = index.with_name(_basename(path_part))
    if len(base_hits) == 1:
        return ResolvedLink(resolved=base_hits[0], confidence=UNIQUE_BASENAME, anchor=anchor)

    suffix = _suffix(path_part)
    if "/" in suffix:
        suffix_hits = index.with_suffix(suffix)
        if len(suffix_hits) == 1:
            return ResolvedLink(resolved=suffix_hits[0], confidence=UNIQUE_SUFFIX, anchor=anchor)

    return ResolvedLink(resolved=None, confidence=UNRESOLVED, anchor=anchor)


def directories_of(files: Collection[str]) -> frozenset[str]:
    """Every ancestor directory of ``files`` (POSIX, no trailing ``/``).

    ``""`` (the repository root) is included whenever there is any file.
    """
    dirs: set[str] = set()
    for path in files:
        parent = _parent(path)
        while parent not in dirs:
            dirs.add(parent)
            if not parent:
                break
            parent = _parent(parent)
    return frozenset(dirs)


def _lookup_cascade(path_part: str, source_dir: str, index: FileIndex) -> str | None:
    source_candidate = _join(source_dir, path_part)
    if source_candidate is not None:
        hit = _lookup_exact(source_candidate, index)
        if hit is not None:
            return hit

    root_candidate = _join("", path_part)
    if root_candidate is not None:
        hit = _lookup_exact(root_candidate, index)
        if hit is not None:
            return hit

    if source_candidate is not None:
        hit = _lookup_ci(source_candidate, index)
        if hit is not None:
            return hit
    if root_candidate is not None and root_candidate != source_candidate:
        hit = _lookup_ci(root_candidate, index)
        if hit is not None:
            return hit
    return None


def _lookup_exact(candidate: str, index: FileIndex) -> str | None:
    if candidate in index:
        return candidate
    hit = _dir_index(candidate, index, case_sensitive=True)
    if hit is not None:
        return hit
    # A directory that holds tracked files is a real target even without a
    # README.md / AGENTS.md / index.md inside it.
    if candidate in index.dirs:
        return candidate
    return None


def _lookup_ci(candidate: str, index: FileIndex) -> str | None:
    hits = index.casefold_hits(candidate)
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        return None
    return _dir_index(candidate, index, case_sensitive=False)


def _dir_index(candidate: str, index: FileIndex, *, case_sensitive: bool) -> str | None:
    for name in DIR_INDEX_NAMES:
        target = f"{candidate}/{name}" if candidate else name
        if case_sensitive:
            if target in index:
                return target
            continue
        hits = index.casefold_hits(target)
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
    index = as_file_index(files)
    base_hits = sorted(index.with_name(_basename(path_part)))
    if len(base_hits) > 1:
        return base_hits
    suffix = _suffix(path_part)
    if "/" in suffix:
        suffix_hits = sorted(index.with_suffix(suffix))
        if len(suffix_hits) > 1:
            return suffix_hits
    return base_hits if len(base_hits) > 1 else []


def fallback_candidates(raw: str, files: Collection[str]) -> list[str]:
    """Ambiguous suffix hits first, then ambiguous basenames. Empty if unique or none."""
    path_part, _anchor = _split_target(raw)
    if not path_part:
        return []
    index = as_file_index(files)
    suffix = _suffix(path_part)
    if "/" in suffix:
        suffix_hits = sorted(index.with_suffix(suffix))
        if len(suffix_hits) > 1:
            return suffix_hits
    base_hits = sorted(index.with_name(_basename(path_part)))
    if len(base_hits) > 1:
        return base_hits
    return []


def link_dir_names(raw: str) -> frozenset[str]:
    """Directory names written in the link (``.``/``..`` and the basename excluded)."""
    path_part, _anchor = _split_target(raw)
    parts = path_part.split("/")[:-1]
    return frozenset(part for part in parts if part not in ("", ".", ".."))


def narrow_candidates(raw: str, candidates: Iterable[str]) -> list[str]:
    """Keep candidates whose directories share at least one name with the link.

    A link without a directory part (a bare basename) has nothing to compare,
    so the candidates pass through unchanged.
    """
    names = link_dir_names(raw)
    items = list(candidates)
    if not names:
        return items
    return [path for path in items if names & set(path.split("/")[:-1])]


def _basename(path: str) -> str:
    """``PurePosixPath(path).name`` for the paths used here, without a path object."""
    return PurePosixPath(path).name if path.endswith(("/", "/.")) else path.rsplit("/", 1)[-1]


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
