"""User-global CLI index storage and source-bound snapshot validation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import warnings
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .embedding import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    attach_embeddings,
    build_embedding_text,
    hash_embedding_text,
)
from ..models import IndexError, SkillRecord, record_to_index_row
from ..source import CatalogSource, fingerprint_key

INDEX_SCHEMA_VERSION = 2
DEFAULT_MAX_AGE_DAYS = 7
MAX_LEXICAL_TEXT_BYTES = 1024 * 1024


def lexical_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def index_records_match(index: Mapping[str, Any], records: Sequence[SkillRecord]) -> bool:
    rows = {row["path"]: row for row in index.get("skills", []) if isinstance(row, dict)}
    return len(rows) == len(records) and all(
        (row := rows.get(record.canonical_id)) is not None
        and row.get("lexicalHash") == lexical_hash(record.body)
        and row.get("embeddingHash") == hash_embedding_text(build_embedding_text(record))
        for record in records
    )


def _is_number_list(value: object, dimensions: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == dimensions
        and all(
            isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item)
            for item in value
        )
    )


def _validate_row(row: object) -> None:
    if not isinstance(row, dict):
        raise IndexError("CLI skill index contains a non-object skill row")
    for key in (
        "path",
        "name",
        "description",
        "tool",
        "plugin",
        "embeddingHash",
        "lexicalHash",
        "lexicalText",
    ):
        if not isinstance(row.get(key), str):
            raise IndexError(f"CLI skill index skill row is missing string field: {key}")
    status = row.get("status")
    if not isinstance(status, dict) or not isinstance(status.get("key"), str):
        raise IndexError("CLI skill index skill row has an invalid status")
    files = row.get("files")
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        raise IndexError("CLI skill index skill row has an invalid files list")
    if not _is_number_list(row.get("embedding"), EMBEDDING_DIMENSIONS):
        raise IndexError("CLI skill index skill row has an invalid embedding")


def validate_index(index: object) -> dict[str, Any]:
    """Validate the complete independent CLI schema before it is used."""

    if not isinstance(index, dict):
        raise IndexError("CLI skill index must contain a JSON object")
    if index.get("schemaVersion") != INDEX_SCHEMA_VERSION:
        raise IndexError("CLI skill index schema version is unsupported; rebuild the index")
    if index.get("embeddingModel") != EMBEDDING_MODEL:
        raise IndexError("CLI skill index embedding model is unsupported; rebuild the index")
    if index.get("embeddingDimensions") != EMBEDDING_DIMENSIONS:
        raise IndexError("CLI skill index embedding dimensions are unsupported; rebuild the index")
    source = index.get("source")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("descriptor"), dict)
        or not isinstance(source.get("fingerprint"), dict)
        or not isinstance(source.get("fingerprintKey"), str)
    ):
        raise IndexError("CLI skill index has invalid source metadata; rebuild the index")
    if "builtAt" in index and not isinstance(index.get("builtAt"), str):
        raise IndexError("CLI skill index has an invalid builtAt; rebuild the index")
    rows = index.get("skills")
    if not isinstance(rows, list):
        raise IndexError("CLI skill index skills must be a list")
    for row in rows:
        _validate_row(row)
    return index


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_built_at(index: Mapping[str, Any]) -> datetime | None:
    """Return the index build time, or None when it is absent or unusable."""

    raw = index.get("builtAt")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def index_age(index: Mapping[str, Any], *, now: datetime | None = None) -> timedelta | None:
    """Return how old an index is; None when unknown (missing, broken, or future)."""

    built_at = parse_built_at(index)
    if built_at is None:
        return None
    age = (now or utc_now()) - built_at
    if age < timedelta(0):
        return None
    return age


def is_fresh(
    index: Mapping[str, Any],
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
    *,
    now: datetime | None = None,
) -> bool:
    """Treat an unknown age as stale so a doubtful index is always rebuilt."""

    if max_age_days <= 0:
        return False
    age = index_age(index, now=now)
    return age is not None and age <= timedelta(days=max_age_days)


def read_index(path: Path, expected_fingerprint: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Read and validate an index, refusing snapshots from another source."""

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IndexError(
            f"CLI skill index not found: {path}; run `skill-tools build-index`"
        ) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndexError(
            f"CLI skill index is unreadable or invalid: {path}; rebuild the index"
        ) from exc
    index = validate_index(parsed)
    if expected_fingerprint is not None:
        actual = index["source"]["fingerprint"]
        if dict(actual) != dict(expected_fingerprint):
            raise IndexError(
                "CLI skill index belongs to another source; run `skill-tools build-index`"
            )
    return index


def _temporary_prefix(path: Path, source: CatalogSource) -> str:
    return f".{path.name}.{fingerprint_key(source.fingerprint)[:16]}."


def write_index(index: Mapping[str, Any], path: Path, source: CatalogSource | None = None) -> None:
    """Write an index using a same-directory temporary file and atomic replace."""

    validated = validate_index(dict(index))
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = _temporary_prefix(path, source) if source is not None else f".{path.name}."
    for temporary in path.parent.glob(f"{prefix}*.tmp"):
        try:
            temporary.unlink()
        except OSError:
            pass
    fd, temporary_name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(validated, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise IndexError(f"could not atomically write CLI skill index: {exc}") from exc


def make_index(
    records: Sequence[SkillRecord],
    source: CatalogSource,
    *,
    previous: Mapping[str, Any] | None = None,
    embedder=None,
    api_key: str | None = None,
    stats: dict[str, int] | None = None,
    built_at: datetime | None = None,
) -> dict[str, Any]:
    """Create a source-bound index, reusing vectors from a compatible snapshot.

    A previous snapshot is adopted whenever its embedding contract matches. The
    source fingerprint is deliberately not part of that check: a row's
    ``embeddingHash`` already decides whether its vector is still correct, while
    the fingerprint changes on any unrelated file in the repository.
    """

    previous_index = None
    if previous is not None:
        try:
            candidate = validate_index(dict(previous))
            if (
                candidate["embeddingModel"] == EMBEDDING_MODEL
                and candidate["embeddingDimensions"] == EMBEDDING_DIMENSIONS
            ):
                previous_index = candidate
        except IndexError:
            previous_index = None
    rows = attach_embeddings(
        records, previous_index, embedder=embedder, api_key=api_key, stats=stats
    )
    indexed_rows = []
    for record, (embedding, embedding_hash) in zip(records, rows, strict=True):
        body_size = len(record.body.encode("utf-8"))
        lexical_text = record.body if body_size <= MAX_LEXICAL_TEXT_BYTES else ""
        if body_size > MAX_LEXICAL_TEXT_BYTES:
            warnings.warn(
                f"{record.canonical_id}: SKILL.md body exceeds the "
                f"{MAX_LEXICAL_TEXT_BYTES}-byte lexical indexing limit; excluded from search",
                stacklevel=2,
            )
        indexed_rows.append(
            record_to_index_row(
                record,
                embedding,
                embedding_hash,
                lexical_hash(record.body),
                lexical_text,
            )
        )
    return {
        "schemaVersion": INDEX_SCHEMA_VERSION,
        "embeddingModel": EMBEDDING_MODEL,
        "embeddingDimensions": EMBEDDING_DIMENSIONS,
        "builtAt": (built_at or utc_now()).isoformat(),
        "source": {
            "descriptor": dict(source.descriptor),
            "fingerprint": dict(source.fingerprint),
            "fingerprintKey": fingerprint_key(source.fingerprint),
        },
        "skills": indexed_rows,
    }
