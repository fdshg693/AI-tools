from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .extract import extract_links
from .resolve import resolve_link
from .store import StoredLink, GraphStore, db_path

TEXT_EXTENSIONS = {".md", ".mdc", ".txt", ".rst"}
SCRIPT_EXTENSIONS = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".mts",
    ".cts",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".bat",
    ".cmd",
    ".rb",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".php",
    ".lua",
    ".r",
    ".pl",
    ".pm",
}
SCRIPT_BASENAMES = frozenset({"justfile", "makefile"})


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class SyncStats:
    updated: int = 0
    skipped: int = 0
    removed: int = 0


def find_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for path in [current, *current.parents]:
        if (path / ".git").exists():
            return path
    return None


def list_git_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(detail or "git ls-files failed")
    files: list[str] = []
    for chunk in result.stdout.split(b"\0"):
        if not chunk:
            continue
        files.append(chunk.decode("utf-8").replace("\\", "/"))
    return files


def is_text_file(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in TEXT_EXTENSIONS


def is_script_file(path: str) -> bool:
    posix = PurePosixPath(path)
    suffix = posix.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return False
    if suffix in SCRIPT_EXTENSIONS:
        return True
    return posix.name.lower() in SCRIPT_BASENAMES


def stored_links_from_text(text: str, source: str, file_set: set[str]) -> list[StoredLink]:
    links: list[StoredLink] = []
    for extracted in extract_links(text):
        resolved = resolve_link(extracted.raw, source, file_set)
        links.append(
            StoredLink(
                raw=extracted.raw,
                kind=extracted.kind,
                line=extracted.line,
                resolved=resolved.resolved,
                confidence=resolved.confidence,
            )
        )
    return links


def read_source_text(root: Path, path: str) -> str:
    full = root.joinpath(*path.split("/"))
    return full.read_text(encoding="utf-8", errors="replace")


def sync_index(root: Path, *, force: bool = False) -> SyncStats:
    all_files = list_git_files(root)
    text_files = [path for path in all_files if is_text_file(path)]
    file_set = set(all_files)
    store = GraphStore(db_path(root))
    try:
        known = store.listed_paths()
        current = set(text_files)
        removed = 0
        for path in known - current:
            store.remove_file(path)
            removed += 1
        updated = 0
        skipped = 0
        for path in text_files:
            full = root.joinpath(*path.split("/"))
            data = full.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if not force and store.file_hash(path) == digest:
                skipped += 1
                continue
            text = data.decode("utf-8", errors="replace")
            links = stored_links_from_text(text, path, file_set)
            store.replace_file(path, digest, full.stat().st_mtime, links)
            updated += 1
        store.set_last_sync(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        return SyncStats(updated=updated, skipped=skipped, removed=removed)
    finally:
        store.close()
