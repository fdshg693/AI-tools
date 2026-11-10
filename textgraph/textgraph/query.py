from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .resolve import UNRESOLVED, lookup_candidates, resolve_link
from .scan import is_text_file, list_git_files
from .store import GraphStore, StoredEdge

UNRESOLVED_CONFIDENCE = UNRESOLVED


@dataclass(frozen=True)
class QueryTarget:
    path: str | None
    candidates: tuple[str, ...]
    error: str | None


@dataclass(frozen=True)
class ImpactResult:
    target: str
    inbound: tuple[StoredEdge, ...]
    outbound: tuple[StoredEdge, ...]
    unresolved: tuple[StoredEdge, ...]


def is_index_stale(root: Path, store: GraphStore) -> bool:
    git_text = {path for path in list_git_files(root) if is_text_file(path)}
    indexed = store.listed_paths()
    if git_text != indexed:
        return True
    mtimes = store.file_mtimes()
    for path in indexed:
        full = root.joinpath(*path.split("/"))
        if not full.is_file():
            return True
        if full.stat().st_mtime > mtimes[path]:
            return True
    return False


def filter_paths(paths: list[str], prefix: str | None) -> list[str]:
    if not prefix:
        return list(paths)
    return [path for path in paths if path.startswith(prefix)]


def collapse_paths(paths: list[str], max_depth: int | None) -> list[str]:
    if max_depth is None:
        return list(paths)
    seen: list[str] = []
    present: set[str] = set()
    for path in paths:
        parts = [part for part in path.split("/") if part]
        if len(parts) <= max_depth:
            entry = path
        else:
            entry = "/".join(parts[:max_depth]) + "/"
        if entry not in present:
            present.add(entry)
            seen.append(entry)
    return seen


def resolve_target(raw: str, root: Path, files: set[str], *, cwd: Path) -> QueryTarget:
    normalized = _to_repo_posix(raw, root)
    if normalized is None:
        return QueryTarget(path=None, candidates=(), error="path is outside the repository")
    source = _cwd_source(root, cwd)
    hit = resolve_link(normalized, source, files)
    if hit.resolved is not None:
        if hit.resolved not in files:
            return QueryTarget(path=None, candidates=(), error="not in index")
        return QueryTarget(path=hit.resolved, candidates=(), error=None)
    candidates = tuple(lookup_candidates(normalized, files))
    if candidates:
        return QueryTarget(path=None, candidates=candidates, error="ambiguous path")
    return QueryTarget(path=None, candidates=(), error="not in index")


def impact_for(store: GraphStore, target: str) -> ImpactResult:
    inbound = tuple(store.inbound_links(target))
    outbound_all = store.outbound_links(target)
    outbound = tuple(edge for edge in outbound_all if edge.confidence != UNRESOLVED_CONFIDENCE)
    unresolved = tuple(edge for edge in outbound_all if edge.confidence == UNRESOLVED_CONFIDENCE)
    return ImpactResult(
        target=target,
        inbound=inbound,
        outbound=outbound,
        unresolved=unresolved,
    )


def impact_json(result: ImpactResult) -> dict[str, object]:
    return {
        "target": result.target,
        "inbound": [
            {
                "source": edge.source,
                "raw": edge.raw,
                "line": edge.line,
                "confidence": edge.confidence,
            }
            for edge in result.inbound
        ],
        "outbound": [
            {
                "raw": edge.raw,
                "resolved": edge.resolved,
                "line": edge.line,
                "confidence": edge.confidence,
            }
            for edge in result.outbound
        ],
        "unresolved": [
            {
                "raw": edge.raw,
                "line": edge.line,
                "confidence": edge.confidence,
            }
            for edge in result.unresolved
        ],
    }


def _to_repo_posix(raw: str, root: Path) -> str | None:
    path = Path(raw)
    if path.is_absolute() or (len(raw) >= 2 and raw[1] == ":"):
        try:
            relative = path.resolve().relative_to(root.resolve())
        except ValueError:
            return None
        return relative.as_posix()
    text = raw.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _cwd_source(root: Path, cwd: Path) -> str:
    try:
        relative = cwd.resolve().relative_to(root.resolve())
    except ValueError:
        return "_query"
    posix = relative.as_posix()
    if posix == ".":
        return "_query"
    return f"{posix}/_query"
