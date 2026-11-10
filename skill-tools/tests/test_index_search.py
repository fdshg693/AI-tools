from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from skill_tools.catalog import discover_catalog
from skill_tools.index import (
    index_age,
    is_fresh,
    make_index,
    read_index,
    utc_now,
    validate_index,
    write_index,
)
from skill_tools.models import IndexError
from skill_tools.index.search import search_index, search_path
from skill_tools.source import LocalSource, display_skill_path


def vector(first: float) -> list[float]:
    values = [0.0] * 1536
    values[0] = first
    return values


def make_source(tmp_path: Path) -> LocalSource:
    root = tmp_path / "source"
    root.mkdir()
    (root / "ai-tools.yaml").write_text(
        "tools:\n  cursor:\n    plugins:\n      - path: plugin\n        kind: plugin\n        skills_layout: direct\n",
        encoding="utf-8",
    )
    for name in ("alpha", "beta"):
        directory = root / "plugin" / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {name} description\n---\n",
            encoding="utf-8",
        )
    return LocalSource(root)


def test_index_is_source_bound_and_atomic(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    alpha_body = source.root / "plugin" / "alpha" / "SKILL.md"
    alpha_body.write_text(
        "---\nname: alpha\ndescription: alpha description\n---\n\n# alpha local body\n",
        encoding="utf-8",
    )
    records = discover_catalog(source)
    calls: list[list[str]] = []

    def embedder(texts):
        calls.append(list(texts))
        return [vector(1.0) for _ in texts]

    index = make_index(records, source, embedder=embedder)
    assert len(calls) == 1
    assert index["schemaVersion"] == 2
    assert "# alpha" in index["skills"][0]["lexicalText"]
    assert index["skills"][0]["lexicalHash"]
    index_path = tmp_path / "cache" / "skill-index.json"
    write_index(index, index_path, source)
    assert read_index(index_path, expected_fingerprint=source.fingerprint)["skills"]
    assert not list(index_path.parent.glob("*.tmp"))
    with pytest.raises(IndexError, match="another source"):
        read_index(index_path, expected_fingerprint={"type": "local", "path": "other"})


def test_lexical_body_is_not_sent_to_the_embedding_provider(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    alpha_body = source.root / "plugin" / "alpha" / "SKILL.md"
    alpha_body.write_text(
        "---\nname: alpha\ndescription: alpha description\n---\n\nprivate lexical-only payload\n",
        encoding="utf-8",
    )
    records = discover_catalog(source)
    calls: list[list[str]] = []

    def embedder(texts):
        calls.append(list(texts))
        return [vector(1.0) for _ in texts]

    index = make_index(records, source, embedder=embedder)

    assert all("private lexical-only payload" not in text for batch in calls for text in batch)
    assert "private lexical-only payload" in index["skills"][0]["lexicalText"]


def test_oversized_body_is_excluded_from_lexical_index(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    alpha_body = source.root / "plugin" / "alpha" / "SKILL.md"
    alpha_body.write_text(
        "---\nname: alpha\ndescription: alpha description\n---\n\n" + "x" * (1024 * 1024 + 1),
        encoding="utf-8",
    )
    records = discover_catalog(source)

    with pytest.warns(UserWarning, match="lexical indexing limit"):
        index = make_index(records, source, embedder=lambda texts: [vector(1.0) for _ in texts])

    row = next(row for row in index["skills"] if row["name"] == "alpha")
    assert row["lexicalText"] == ""
    assert row["lexicalHash"]


def test_embedding_hash_reuse_only_reembeds_changed_metadata(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    records = discover_catalog(source)
    calls: list[list[str]] = []

    def embedder(texts):
        calls.append(list(texts))
        return [vector(1.0) for _ in texts]

    first = make_index(records, source, embedder=embedder)
    assert len(calls[0]) == 2
    calls.clear()
    reused = make_index(records, source, previous=first, embedder=embedder)
    assert calls == []
    assert reused["skills"][0]["embedding"] == first["skills"][0]["embedding"]


def test_search_has_stable_path_tie_break_and_cwd_independent_path(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    records = discover_catalog(source)
    index = make_index(records, source, embedder=lambda texts: [vector(1.0) for _ in texts])
    index_path = tmp_path / "index.json"
    write_index(index, index_path, source)
    results = search_path(
        "anything",
        index_path,
        expected_fingerprint=source.fingerprint,
        embedder=lambda texts: [vector(1.0) for _ in texts],
    )
    assert [result.path for result in results] == sorted(result.path for result in results)
    assert all(result.score > 0 for result in results)
    expected = {display_skill_path(record.canonical_id, source.descriptor) for record in records}
    assert {result.path for result in results} == expected
    assert all(Path(result.path).is_absolute() for result in results)
    with pytest.raises(IndexError, match="not found"):
        read_index(tmp_path / "missing.json")


def test_hybrid_search_ranks_body_only_terms_and_returns_a_snippet(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    beta_skill = source.root / "plugin" / "beta" / "SKILL.md"
    beta_skill.write_text(
        "---\nname: beta\ndescription: beta description\n---\n\n"
        "Use the quasar-transactions procedure before deployment.\n",
        encoding="utf-8",
    )
    records = discover_catalog(LocalSource(source.root))
    index = make_index(records, source, embedder=lambda texts: [vector(1.0) for _ in texts])
    calls: list[list[str]] = []

    def query_embedder(texts):
        calls.append(list(texts))
        return [vector(1.0) for _ in texts]

    results = search_index("quasar-transactions", index, top_k=2, embedder=query_embedder)

    assert results[0].name == "beta"
    assert results[0].canonical_id == "plugin/beta/SKILL.md"
    assert "quasar-transactions" in results[0].snippet
    assert calls == [["quasar-transactions"]]


def test_search_omits_snippets_without_a_lexical_match(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    index = make_index(
        discover_catalog(source), source, embedder=lambda texts: [vector(1.0) for _ in texts]
    )
    results = search_index("unmatchedterm", index, embedder=lambda texts: [vector(1.0)])

    assert all(result.snippet is None for result in results)


def test_lexical_search_casefolds_unicode_and_handles_cjk_terms(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    beta = source.root / "plugin" / "beta" / "SKILL.md"
    beta.write_text(
        "---\nname: beta\ndescription: beta description\n---\n\n"
        "設定ファイルの鮮度を確認する手順。\n",
        encoding="utf-8",
    )
    index = make_index(
        discover_catalog(LocalSource(source.root)),
        source,
        embedder=lambda texts: [vector(1.0) for _ in texts],
    )

    results = search_index("鮮度", index, embedder=lambda texts: [vector(1.0)])

    assert results[0].name == "beta"
    assert "鮮度" in results[0].snippet


def test_old_schema_requires_explicit_index_rebuild(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    index = make_index(
        discover_catalog(source), source, embedder=lambda texts: [vector(1.0) for _ in texts]
    )
    old = dict(index, schemaVersion=1)

    with pytest.raises(IndexError, match="schema version.*rebuild"):
        validate_index(old)


def test_built_at_is_recorded_and_optional(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    records = discover_catalog(source)
    index = make_index(records, source, embedder=lambda texts: [vector(1.0) for _ in texts])
    assert isinstance(index["builtAt"], str)
    assert is_fresh(index)
    assert index_age(index) is not None

    legacy = dict(index)
    legacy.pop("builtAt")
    assert validate_index(legacy)["skills"]
    assert index_age(legacy) is None
    assert not is_fresh(legacy)

    index_path = tmp_path / "index.json"
    write_index(legacy, index_path, source)
    assert "builtAt" not in read_index(index_path)

    broken = dict(index, builtAt="not-a-timestamp")
    assert index_age(broken) is None
    assert not is_fresh(broken)

    future = dict(index, builtAt=(utc_now() + timedelta(days=1)).isoformat())
    assert index_age(future) is None
    assert not is_fresh(future)

    with pytest.raises(IndexError, match="builtAt"):
        validate_index(dict(index, builtAt=123))


def test_freshness_window_is_bounded_by_max_age(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    records = discover_catalog(source)
    index = make_index(
        records,
        source,
        embedder=lambda texts: [vector(1.0) for _ in texts],
        built_at=utc_now() - timedelta(days=3),
    )
    assert is_fresh(index, 7)
    assert not is_fresh(index, 1)
    assert not is_fresh(index, 0)


def test_vectors_are_reused_when_only_the_fingerprint_changed(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    records = discover_catalog(source)
    calls: list[list[str]] = []

    def embedder(texts):
        calls.append(list(texts))
        return [vector(1.0) for _ in texts]

    first = make_index(records, source, embedder=embedder)
    calls.clear()

    (source.root / "unrelated.md").write_text("an unrelated change\n", encoding="utf-8")
    changed = LocalSource(source.root)
    assert dict(changed.fingerprint) != dict(source.fingerprint)

    stats: dict[str, int] = {}
    reused = make_index(
        discover_catalog(changed), changed, previous=first, embedder=embedder, stats=stats
    )
    assert calls == []
    assert stats == {"embedded": 0, "reused": 2}
    assert reused["skills"][0]["embedding"] == first["skills"][0]["embedding"]


def test_vectors_are_reused_when_a_skill_moves(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    first = make_index(
        discover_catalog(source), source, embedder=lambda texts: [vector(1.0) for _ in texts]
    )

    (source.root / "plugin" / "alpha").rename(source.root / "plugin" / "alpha-moved")
    moved = LocalSource(source.root)
    calls: list[list[str]] = []

    def embedder(texts):
        calls.append(list(texts))
        return [vector(0.5) for _ in texts]

    stats: dict[str, int] = {}
    rebuilt = make_index(
        discover_catalog(moved), moved, previous=first, embedder=embedder, stats=stats
    )
    assert calls == []
    assert stats == {"embedded": 0, "reused": 2}
    assert {row["path"] for row in rebuilt["skills"]} != {row["path"] for row in first["skills"]}


def test_changed_description_is_reembedded(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    first = make_index(
        discover_catalog(source), source, embedder=lambda texts: [vector(1.0) for _ in texts]
    )
    (source.root / "plugin" / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: alpha has a new description\n---\n", encoding="utf-8"
    )
    changed = LocalSource(source.root)
    stats: dict[str, int] = {}
    make_index(
        discover_catalog(changed),
        changed,
        previous=first,
        embedder=lambda texts: [vector(0.5) for _ in texts],
        stats=stats,
    )
    assert stats == {"embedded": 1, "reused": 1}
