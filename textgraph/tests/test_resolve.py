from __future__ import annotations

from textgraph.resolve import ResolvedLink, fallback_candidates, lookup_candidates, resolve_link

FILES = {
    "README.md",
    "docs/guide.md",
    "docs/README.md",
    "docs/intro.md",
    "notes/unique-name.md",
    "old/deep/file.md",
    "other/file.md",
    "a/SKILL.md",
    "b/SKILL.md",
}


def test_resolves_relative_to_source_directory() -> None:
    assert resolve_link("./guide.md", "docs/intro.md", FILES) == ResolvedLink(
        resolved="docs/guide.md",
        confidence="exact",
        anchor=None,
    )


def test_resolves_relative_to_repo_root() -> None:
    assert resolve_link("docs/guide.md", "README.md", FILES) == ResolvedLink(
        resolved="docs/guide.md",
        confidence="exact",
        anchor=None,
    )


def test_resolves_case_insensitively() -> None:
    assert resolve_link("Docs/Guide.md", "README.md", FILES) == ResolvedLink(
        resolved="docs/guide.md",
        confidence="exact",
        anchor=None,
    )


def test_appends_md_when_extension_is_missing() -> None:
    assert resolve_link("docs/guide", "README.md", FILES) == ResolvedLink(
        resolved="docs/guide.md",
        confidence="exact",
        anchor=None,
    )


def test_unique_basename() -> None:
    assert resolve_link("unique-name.md", "README.md", FILES) == ResolvedLink(
        resolved="notes/unique-name.md",
        confidence="unique-basename",
        anchor=None,
    )


def test_unique_suffix_when_basename_is_ambiguous() -> None:
    assert resolve_link("deep/file.md", "README.md", FILES) == ResolvedLink(
        resolved="old/deep/file.md",
        confidence="unique-suffix",
        anchor=None,
    )


def test_ambiguous_basename_without_unique_suffix_is_unresolved() -> None:
    assert resolve_link("SKILL.md", "README.md", FILES) == ResolvedLink(
        resolved=None,
        confidence="unresolved",
        anchor=None,
    )


def test_lookup_candidates_lists_ambiguous_basenames() -> None:
    assert lookup_candidates("SKILL.md", FILES) == ["a/SKILL.md", "b/SKILL.md"]
    assert lookup_candidates("guide.md", FILES) == []


def test_fallback_candidates_prefers_ambiguous_suffix() -> None:
    files = {"a/deep/file.md", "b/deep/file.md", "c/file.md"}
    assert fallback_candidates("deep/file.md", files) == [
        "a/deep/file.md",
        "b/deep/file.md",
    ]
    assert fallback_candidates("SKILL.md", FILES) == ["a/SKILL.md", "b/SKILL.md"]


def test_directory_prefers_readme_then_agents_then_index() -> None:
    assert resolve_link("docs", "README.md", FILES).resolved == "docs/README.md"
    agents_only = {"pkg/AGENTS.md", "pkg/index.md"}
    assert resolve_link("pkg", "README.md", agents_only).resolved == "pkg/AGENTS.md"
    index_only = {"pkg/index.md"}
    assert resolve_link("pkg", "README.md", index_only).resolved == "pkg/index.md"


def test_keeps_anchor_but_resolves_path() -> None:
    assert resolve_link("./guide.md#section", "docs/intro.md", FILES) == ResolvedLink(
        resolved="docs/guide.md",
        confidence="exact",
        anchor="section",
    )


def test_strips_at_prefix_before_resolving() -> None:
    assert resolve_link("@./README.md", "docs/intro.md", FILES) == ResolvedLink(
        resolved="docs/README.md",
        confidence="exact",
        anchor=None,
    )
