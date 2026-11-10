from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

INDEX_DIR = ".textgraph"
DB_NAME = "graph.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY,
  hash TEXT NOT NULL,
  mtime REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS links (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  raw TEXT NOT NULL,
  kind TEXT NOT NULL,
  line INTEGER NOT NULL,
  resolved TEXT,
  confidence TEXT NOT NULL,
  FOREIGN KEY (source) REFERENCES files(path) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS links_source ON links(source);
CREATE INDEX IF NOT EXISTS links_resolved ON links(resolved);
CREATE INDEX IF NOT EXISTS links_confidence ON links(confidence);
"""


def db_path(root: Path) -> Path:
    return root / INDEX_DIR / DB_NAME


@dataclass(frozen=True)
class StoredLink:
    raw: str
    kind: str
    line: int
    resolved: str | None
    confidence: str


@dataclass(frozen=True)
class StoredEdge:
    source: str
    raw: str
    kind: str
    line: int
    resolved: str | None
    confidence: str


class GraphStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def listed_paths(self) -> set[str]:
        rows = self._conn.execute("SELECT path FROM files").fetchall()
        return {row[0] for row in rows}

    def list_files(self) -> list[str]:
        rows = self._conn.execute("SELECT path FROM files ORDER BY path").fetchall()
        return [str(row[0]) for row in rows]

    def file_mtimes(self) -> dict[str, float]:
        rows = self._conn.execute("SELECT path, mtime FROM files").fetchall()
        return {str(row[0]): float(row[1]) for row in rows}

    def inbound_links(self, target: str) -> list[StoredEdge]:
        rows = self._conn.execute(
            "SELECT source, raw, kind, line, resolved, confidence FROM links"
            " WHERE resolved = ? ORDER BY source, line, id",
            (target,),
        ).fetchall()
        return [_edge(row) for row in rows]

    def outbound_links(self, source: str) -> list[StoredEdge]:
        rows = self._conn.execute(
            "SELECT source, raw, kind, line, resolved, confidence FROM links"
            " WHERE source = ? ORDER BY line, id",
            (source,),
        ).fetchall()
        return [_edge(row) for row in rows]

    def all_links(self) -> list[StoredEdge]:
        rows = self._conn.execute(
            "SELECT source, raw, kind, line, resolved, confidence FROM links"
            " ORDER BY source, line, id"
        ).fetchall()
        return [_edge(row) for row in rows]

    def file_hash(self, path: str) -> str | None:
        row = self._conn.execute("SELECT hash FROM files WHERE path = ?", (path,)).fetchone()
        return None if row is None else str(row[0])

    def replace_file(self, path: str, digest: str, mtime: float, links: list[StoredLink]) -> None:
        self._conn.execute("DELETE FROM links WHERE source = ?", (path,))
        self._conn.execute("DELETE FROM files WHERE path = ?", (path,))
        self._conn.execute(
            "INSERT INTO files (path, hash, mtime) VALUES (?, ?, ?)",
            (path, digest, mtime),
        )
        self._conn.executemany(
            "INSERT INTO links (source, raw, kind, line, resolved, confidence)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (path, link.raw, link.kind, link.line, link.resolved, link.confidence)
                for link in links
            ],
        )
        self._conn.commit()

    def remove_file(self, path: str) -> None:
        self._conn.execute("DELETE FROM links WHERE source = ?", (path,))
        self._conn.execute("DELETE FROM files WHERE path = ?", (path,))
        self._conn.commit()

    def counts(self) -> tuple[int, int, int]:
        files = int(self._conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
        links = int(self._conn.execute("SELECT COUNT(*) FROM links").fetchone()[0])
        unresolved = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM links WHERE confidence = 'unresolved'"
            ).fetchone()[0]
        )
        return files, links, unresolved

    def last_sync(self) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = 'last_sync'").fetchone()
        return None if row is None else str(row[0])

    def set_last_sync(self, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES ('last_sync', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (value,),
        )
        self._conn.commit()


def _edge(row: tuple[object, ...]) -> StoredEdge:
    resolved = row[4]
    return StoredEdge(
        source=str(row[0]),
        raw=str(row[1]),
        kind=str(row[2]),
        line=int(row[3]),
        resolved=None if resolved is None else str(resolved),
        confidence=str(row[5]),
    )
