"""Search and build-index commands."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ..catalog import discover_catalog
from ..config import create_source
from ..index.build import (
    DEFAULT_MAX_AGE_DAYS,
    index_age,
    index_records_match,
    is_fresh,
    make_index,
    read_index,
    write_index,
)
from ..index.embedding import EMBEDDING_MODEL, missing_api_key_message, resolve_api_key
from ..index.search import search_index
from ..models import CatalogError, EmbeddingError, IndexError, SearchResult
from .arguments import (
    _add_runtime_arguments,
    _configured_source_description,
    _index_matches_configured_source,
    _load_runtime_config,
    _source_description,
)


def _add_search_command(commands) -> None:
    search = commands.add_parser("search", help="search the CLI-only global index snapshot")
    _add_runtime_arguments(search)
    search.add_argument("--query", "-q", required=True, help="search query")
    search.add_argument("--top", "-k", type=int, default=10, help="number of results to show")
    search.add_argument("--json", action="store_true", help="write results as JSON")


def _add_build_index_command(commands) -> None:
    build_index = commands.add_parser(
        "build-index", help="rebuild the CLI-only global index from the configured source"
    )
    _add_runtime_arguments(build_index)
    build_index.add_argument(
        "--force",
        action="store_true",
        help="rebuild even when the existing index is still fresh",
    )
    build_index.add_argument(
        "--max-age-days",
        type=float,
        default=DEFAULT_MAX_AGE_DAYS,
        help=(
            "skip the rebuild while the existing index is younger than this "
            f"(default: {DEFAULT_MAX_AGE_DAYS}; 0 always rebuilds)"
        ),
    )


def _print_warnings(caught: Sequence[warnings.WarningMessage]) -> None:
    for warning in caught:
        print(f"warning: {warning.message}", file=sys.stderr)


def _read_search_index(config):
    """Load the snapshot, matching on source identity rather than fingerprint.

    A local fingerprint covers every visible file in the repository, so it drifts
    on changes that cannot affect the stored vectors. Searching is therefore a
    warning, not an error, when only the fingerprint moved.
    """

    index = read_index(config.index.path)
    if not _index_matches_configured_source(index, config):
        raise IndexError("CLI skill index belongs to another source; run `skill-tools build-index`")
    age = index_age(index)
    if age is None:
        print(
            "warning: CLI skill index has no known build time; "
            "consider running `skill-tools build-index`",
            file=sys.stderr,
        )
    elif age.days > DEFAULT_MAX_AGE_DAYS:
        print(
            f"warning: CLI skill index is {age.days} days old; "
            "consider running `skill-tools build-index`",
            file=sys.stderr,
        )
    return index


def _result_payload(result: SearchResult) -> dict[str, Any]:
    return {
        "path": result.path,
        "canonicalId": result.canonical_id,
        "name": result.name,
        "description": result.description,
        "tool": result.tool,
        "plugin": result.plugin,
        "status": {"key": result.status},
        "score": result.score,
        "snippet": result.snippet,
    }


def _print_search_table(results: Sequence[SearchResult]) -> None:
    if not results:
        print("(no results)")
        return
    print("\t".join(["score", "canonical_id", "path", "name", "snippet"]))
    for result in results:
        print(
            "\t".join(
                [
                    f"{result.score:.4f}",
                    result.canonical_id,
                    result.path,
                    result.name,
                    result.snippet or "",
                ]
            )
        )


def _resolve_api_key_or_raise(embedder) -> str | None:
    if embedder is not None:
        return None
    api_key = resolve_api_key()
    if not api_key:
        raise EmbeddingError(missing_api_key_message())
    return api_key


def _command_search(
    args: argparse.Namespace,
    cwd: Path,
    embedder: Callable[[Sequence[str]], Sequence[Sequence[float]]] | None,
) -> int:
    config = _load_runtime_config(args, cwd)
    if args.top < 0:
        raise CatalogError("--top must not be negative")
    api_key = _resolve_api_key_or_raise(embedder)
    index = _read_search_index(config)
    results = search_index(args.query, index, top_k=args.top, embedder=embedder, api_key=api_key)
    if args.json:
        print(json.dumps([_result_payload(result) for result in results], indent=2))
    else:
        _print_search_table(results)
    return 0


def _existing_index(config):
    try:
        return read_index(config.index.path)
    except IndexError:
        return None


def _skip_for_freshness(args: argparse.Namespace, config, previous, records) -> bool:
    """Skip only when both index age and searchable bodies are current."""

    if getattr(args, "force", False) or previous is None:
        return False
    max_age_days = getattr(args, "max_age_days", DEFAULT_MAX_AGE_DAYS)
    if not _index_matches_configured_source(previous, config):
        return False
    return is_fresh(previous, max_age_days) and index_records_match(previous, records)


def _command_build_index(
    args: argparse.Namespace,
    cwd: Path,
    embedder: Callable[[Sequence[str]], Sequence[Sequence[float]]] | None,
) -> int:
    config = _load_runtime_config(args, cwd)
    previous = _existing_index(config)
    source = create_source(config)
    records = discover_catalog(source)
    if _skip_for_freshness(args, config, previous, records):
        print(
            f"Index is up to date: {config.index.path} "
            f"(builtAt: {previous.get('builtAt')}); use --force to rebuild"
        )
        print(f"source: {_configured_source_description(config)}", file=sys.stderr)
        return 0
    stats: dict[str, int] = {}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _resolve_api_key_or_raise(embedder)
        index = make_index(records, source, previous=previous, embedder=embedder, stats=stats)
        write_index(index, config.index.path, source)
    _print_warnings(caught)
    print(
        f"Wrote {len(index['skills'])} skills to {config.index.path} "
        f"(embeddingModel: {index.get('embeddingModel', EMBEDDING_MODEL)}, "
        f"embedded: {stats.get('embedded', 0)}, reused: {stats.get('reused', 0)})"
    )
    print(f"source: {_source_description(source)}", file=sys.stderr)
    return 0
