"""Independent OpenRouter embedding contract for the skill-tools index."""

from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ..locations import project_root
from ..models import EmbeddingError, SkillRecord

EMBEDDING_MODEL = "openai/text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
EMBEDDING_TIMEOUT_SECONDS = 60
EMBEDDING_BATCH_SIZE = 64


def build_embedding_text(record: SkillRecord) -> str:
    return f"name: {record.name}\ndescription: {record.description}"


def hash_embedding_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tool_env_path() -> Path:
    """Return the fixed .env path for the source checkout of this tool."""

    return project_root() / ".env"


def _read_env_key(path: Path, key: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.strip() or None
    return None


def missing_api_key_message(key: str = "OPENROUTER_API_KEY", env_path: Path | None = None) -> str:
    env_path = (env_path or _tool_env_path()).resolve()
    env_state = "空で設定されている" if key in os.environ else "未設定"
    if env_path.is_file():
        file_state = f"{env_path} はありますが、{key} が無いか空です。"
    else:
        file_state = f"想定した .env は {env_path} ですが、ファイルがありません。"
    return f"{key} が解決できません。\n環境変数 {key} は{env_state}です。\n{file_state}"


def resolve_api_key(env_path: Path | None = None) -> str | None:
    """Use the process environment first, then this tool's fixed .env path."""

    key = "OPENROUTER_API_KEY"
    if key in os.environ:
        return os.environ[key].strip() or None
    fallback = (env_path or _tool_env_path()).resolve()
    value = _read_env_key(fallback, key)
    return value


def _validate_embedding(value: object, index: int) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != EMBEDDING_DIMENSIONS
        or any(
            not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item)
            for item in value
        )
    ):
        raise EmbeddingError(
            f"embedding at index {index} must contain {EMBEDDING_DIMENSIONS} finite numbers"
        )
    return [float(item) for item in value]


def fetch_embeddings(
    texts: Sequence[str],
    *,
    api_key: str,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
    timeout: int = EMBEDDING_TIMEOUT_SECONDS,
) -> list[list[float]]:
    """Call OpenRouter and validate its response without a site dependency."""

    if not api_key:
        raise EmbeddingError(missing_api_key_message())
    if not texts:
        return []
    request = urllib.request.Request(
        OPENROUTER_EMBEDDINGS_URL,
        data=json.dumps(
            {
                "model": EMBEDDING_MODEL,
                "input": list(texts),
                "dimensions": EMBEDDING_DIMENSIONS,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise EmbeddingError(
            f"OpenRouter embeddings failed ({exc.code}){f': {detail}' if detail else ''}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise EmbeddingError(f"could not read OpenRouter embeddings: {exc}") from exc

    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) != len(texts):
        raise EmbeddingError("OpenRouter embeddings response has unexpected shape")
    if not all(isinstance(row, dict) for row in rows):
        raise EmbeddingError("OpenRouter embeddings response has unexpected shape")
    by_index = {row.get("index"): row.get("embedding") for row in rows if isinstance(row, dict)}
    return [
        _validate_embedding(by_index.get(index, rows[index].get("embedding")), index)
        for index in range(len(texts))
    ]


def fetch_embeddings_batched(
    texts: Sequence[str],
    *,
    api_key: str,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> list[list[float]]:
    result: list[list[float]] = []
    for offset in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        result.extend(
            fetch_embeddings(
                texts[offset : offset + EMBEDDING_BATCH_SIZE],
                api_key=api_key,
                urlopen=urlopen,
            )
        )
    return result


def attach_embeddings(
    records: Sequence[SkillRecord],
    previous: dict[str, Any] | None,
    *,
    embedder: Callable[[Sequence[str]], Sequence[Sequence[float]]] | None = None,
    api_key: str | None = None,
    stats: dict[str, int] | None = None,
) -> list[tuple[list[float], str]]:
    """Reuse vectors by metadata hash and embed only changed records.

    Reuse is keyed first by canonical path and then by ``embeddingHash`` alone,
    so a skill that only moved or was renamed keeps its vector.
    """

    previous_by_path: dict[str, dict[str, Any]] = {}
    previous_by_hash: dict[str, list[float]] = {}
    for row in (previous or {}).get("skills", []):
        if not isinstance(row, dict):
            continue
        embedding = row.get("embedding")
        if (
            isinstance(row.get("path"), str)
            and isinstance(row.get("embeddingHash"), str)
            and isinstance(embedding, list)
            and len(embedding) == EMBEDDING_DIMENSIONS
        ):
            try:
                validated = _validate_embedding(embedding, 0)
            except EmbeddingError:
                continue
            previous_by_path[row["path"]] = {
                "hash": row["embeddingHash"],
                "embedding": validated,
            }
            previous_by_hash.setdefault(row["embeddingHash"], validated)

    prepared: list[tuple[SkillRecord, str, str, list[float] | None]] = []
    for record in records:
        text = build_embedding_text(record)
        embedding_hash = hash_embedding_text(text)
        previous_row = previous_by_path.get(record.canonical_id)
        if previous_row is not None and previous_row["hash"] == embedding_hash:
            reusable = previous_row["embedding"]
        else:
            reusable = previous_by_hash.get(embedding_hash)
        prepared.append((record, text, embedding_hash, reusable))

    pending = [entry for entry in prepared if entry[3] is None]
    if stats is not None:
        stats["embedded"] = len(pending)
        stats["reused"] = len(prepared) - len(pending)
    if pending:
        if embedder is None:
            api_key = api_key or resolve_api_key()
            if not api_key:
                raise EmbeddingError(missing_api_key_message())
            fetched = fetch_embeddings_batched(
                [entry[1] for entry in pending],
                api_key=api_key,
            )
        else:
            fetched = list(embedder([entry[1] for entry in pending]))
        if len(fetched) != len(pending):
            raise EmbeddingError("embedding count does not match skills needing computation")
    else:
        fetched = []

    result: list[tuple[list[float], str]] = []
    pending_index = 0
    for _, _, embedding_hash, reusable in prepared:
        if reusable is not None:
            result.append((reusable, embedding_hash))
        else:
            result.append(
                (_validate_embedding(list(fetched[pending_index]), pending_index), embedding_hash)
            )
            pending_index += 1
    return result
