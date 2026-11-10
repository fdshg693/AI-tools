"""Deterministic cosine search over the CLI-only index snapshot."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .embedding import (
    EMBEDDING_DIMENSIONS,
    fetch_embeddings,
    missing_api_key_message,
    resolve_api_key,
)
from .build import read_index
from ..models import EmbeddingError, SearchResult
from ..source import display_skill_path

_TOKEN = re.compile(r"\w+", re.UNICODE)
_SNIPPET_LIMIT = 240
_RRF_K = 60


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return float("nan")
    if any(not math.isfinite(value) for value in (*left, *right)):
        return float("nan")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return float("nan")
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


def _tokens(text: str) -> list[str]:
    result: list[str] = []
    for token in _TOKEN.findall(text.casefold()):
        if any("\u3040" <= char <= "\u30ff" or "\u3400" <= char <= "\u9fff" for char in token):
            result.extend(token[index : index + 2] for index in range(max(1, len(token) - 1)))
        else:
            result.append(token)
    return result


def _bm25_scores(query: str, rows: Sequence[Mapping[str, Any]]) -> list[tuple[int, float]]:
    query_terms = sorted(set(_tokens(query)))
    documents = [_tokens(row["lexicalText"]) for row in rows]
    if not query_terms:
        return []
    average_length = sum(map(len, documents)) / max(1, len(documents))
    scores: list[tuple[int, float]] = []
    for term in query_terms:
        frequencies = [document.count(term) for document in documents]
        document_frequency = sum(frequency > 0 for frequency in frequencies)
        if not document_frequency:
            continue
        inverse_frequency = math.log(
            1 + (len(documents) - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        for index, frequency in enumerate(frequencies):
            if frequency == 0:
                continue
            length_norm = 1.5 * (1 - 0.75 + 0.75 * len(documents[index]) / max(1, average_length))
            scores.append((index, inverse_frequency * frequency * 2.5 / (frequency + length_norm)))
    totals: dict[int, float] = {}
    for index, score in scores:
        totals[index] = totals.get(index, 0.0) + score
    return sorted(totals.items(), key=lambda item: (-item[1], rows[item[0]]["path"]))


def _snippet(text: str, query: str) -> str | None:
    flat = re.sub(r"\s+", " ", text).strip()
    folded = flat.casefold()
    positions = [folded.find(token) for token in _tokens(query) if folded.find(token) >= 0]
    if not positions:
        return None
    start_at = min(positions)
    start = max(0, min(start_at - _SNIPPET_LIMIT // 3, len(flat) - _SNIPPET_LIMIT))
    end = min(len(flat), start + _SNIPPET_LIMIT)
    snippet = flat[start:end]
    if start:
        snippet = "..." + snippet
    if end < len(flat):
        snippet += "..."
    return snippet


def search_index(
    query: str,
    index: Mapping[str, Any],
    *,
    top_k: int = 10,
    embedder: Callable[[Sequence[str]], Sequence[Sequence[float]]] | None = None,
    api_key: str | None = None,
) -> list[SearchResult]:
    """Rank only immutable snapshot rows; no source tree is rescanned."""

    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if top_k < 0:
        raise ValueError("top_k must not be negative")
    if embedder is None:
        api_key = api_key or resolve_api_key()
        if not api_key:
            raise EmbeddingError(missing_api_key_message())
        vectors = fetch_embeddings([query], api_key=api_key)
    else:
        vectors = list(embedder([query]))
    if len(vectors) != 1 or len(vectors[0]) != EMBEDDING_DIMENSIONS:
        raise EmbeddingError("query embedding has unexpected dimensions")
    query_embedding = [float(value) for value in vectors[0]]
    descriptor = index.get("source", {}).get("descriptor")
    if not isinstance(descriptor, dict):
        descriptor = None
    rows = index["skills"]
    semantic: list[tuple[int, float]] = []
    for row_index, row in enumerate(rows):
        score = cosine_similarity(query_embedding, row["embedding"])
        if not math.isfinite(score):
            continue
        semantic.append((row_index, score))
    semantic.sort(key=lambda item: (-item[1], rows[item[0]]["path"]))
    semantic_ranks = {row_index: rank for rank, (row_index, _) in enumerate(semantic, 1)}
    lexical = _bm25_scores(query, rows)
    lexical_ranks = {row_index: rank for rank, (row_index, _) in enumerate(lexical, 1)}
    candidates = set(semantic_ranks) | set(lexical_ranks)
    ranked = sorted(
        candidates,
        key=lambda row_index: (
            -sum(
                1 / (_RRF_K + rank)
                for rank in (semantic_ranks.get(row_index), lexical_ranks.get(row_index))
                if rank is not None
            ),
            rows[row_index]["path"],
        ),
    )
    results: list[SearchResult] = []
    for row_index in ranked[:top_k]:
        row = rows[row_index]
        score = sum(
            1 / (_RRF_K + rank)
            for rank in (semantic_ranks.get(row_index), lexical_ranks.get(row_index))
            if rank is not None
        )
        results.append(
            SearchResult(
                path=display_skill_path(row["path"], descriptor),
                canonical_id=row["path"],
                name=row["name"],
                description=row["description"],
                tool=row["tool"],
                plugin=row["plugin"],
                status=row["status"]["key"],
                score=score,
                snippet=_snippet(row["lexicalText"], query),
            )
        )
    return results


def search_path(
    query: str,
    index_path: Path,
    *,
    expected_fingerprint: Mapping[str, str] | None = None,
    top_k: int = 10,
    embedder: Callable[[Sequence[str]], Sequence[Sequence[float]]] | None = None,
    api_key: str | None = None,
) -> list[SearchResult]:
    """Load a validated source-bound index and search its snapshot."""

    index = read_index(index_path, expected_fingerprint=expected_fingerprint)
    return search_index(query, index, top_k=top_k, embedder=embedder, api_key=api_key)
