"""Index build, embedding, and search."""

from __future__ import annotations

from .embedding import (
    EMBEDDING_MODEL,
    EMBEDDING_DIMENSIONS,
    OPENROUTER_EMBEDDINGS_URL,
    EMBEDDING_TIMEOUT_SECONDS,
    EMBEDDING_BATCH_SIZE,
    build_embedding_text,
    hash_embedding_text,
    missing_api_key_message,
    resolve_api_key,
    fetch_embeddings,
    fetch_embeddings_batched,
    attach_embeddings,
)

from .build import (
    INDEX_SCHEMA_VERSION,
    DEFAULT_MAX_AGE_DAYS,
    MAX_LEXICAL_TEXT_BYTES,
    lexical_hash,
    index_records_match,
    validate_index,
    utc_now,
    parse_built_at,
    index_age,
    is_fresh,
    read_index,
    write_index,
    make_index,
)

from .search import (
    cosine_similarity,
    search_index,
    search_path,
)

__all__ = [
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSIONS",
    "OPENROUTER_EMBEDDINGS_URL",
    "EMBEDDING_TIMEOUT_SECONDS",
    "EMBEDDING_BATCH_SIZE",
    "build_embedding_text",
    "hash_embedding_text",
    "missing_api_key_message",
    "resolve_api_key",
    "fetch_embeddings",
    "fetch_embeddings_batched",
    "attach_embeddings",
    "INDEX_SCHEMA_VERSION",
    "DEFAULT_MAX_AGE_DAYS",
    "MAX_LEXICAL_TEXT_BYTES",
    "lexical_hash",
    "index_records_match",
    "validate_index",
    "utc_now",
    "parse_built_at",
    "index_age",
    "is_fresh",
    "read_index",
    "write_index",
    "make_index",
    "cosine_similarity",
    "search_index",
    "search_path",
]
