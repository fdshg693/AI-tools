from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath

import pytest

from skill_tools.models import CatalogError, SourceError
from skill_tools.install.policy import (
    GITIGNORE_PATH,
    INCLUDE_PATH,
    BundlePolicy,
    load_bundle_policy,
)


class FakeSource:
    """Minimal ``CatalogSource`` surface used by the policy loader."""

    def __init__(self, files: Mapping[str, bytes]) -> None:
        self.files = {PurePosixPath(name): content for name, content in files.items()}

    @property
    def descriptor(self) -> Mapping[str, str]:
        return {"type": "test"}

    @property
    def fingerprint(self) -> Mapping[str, str]:
        return {"type": "test"}

    def list_files(self, roots: Iterable[PurePosixPath]) -> tuple[PurePosixPath, ...]:
        roots = tuple(roots)
        return tuple(
            sorted(path for path in self.files if any(path.is_relative_to(root) for root in roots))
        )

    def read_file(self, path: PurePosixPath) -> bytes:
        if path not in self.files:
            raise SourceError(f"source file does not exist: {path}")
        return self.files[path]


def test_defaults_exclude_caches_and_env_case_insensitively() -> None:
    policy = BundlePolicy()
    assert policy.keep(PurePosixPath("SKILL.md")) is True
    assert policy.keep(PurePosixPath("references/guide.md")) is True
    for excluded in (
        ".venv/lib/python3.11/site-packages/x.py",
        "__pycache__/module.pyc",
        "node_modules/pkg/index.js",
        ".pytest_cache/v/cache/lastfailed",
        ".env",
        ".ENV",
        "nested/.Env",
    ):
        assert policy.keep(PurePosixPath(excluded)) is False, excluded


def test_default_directory_pattern_covers_nested_files() -> None:
    """A trailing-slash pattern must exclude everything below the directory."""

    policy = BundlePolicy()
    assert policy.keep(PurePosixPath(".venv/lib/x.py")) is False
    assert policy.keep(PurePosixPath("deep/.venv/lib/x.py")) is False


def test_gitignore_negation_restores_default_exclusion() -> None:
    policy = BundlePolicy(exclude_lines=("!.env",))
    assert policy.keep(PurePosixPath(".env")) is True
    assert policy.keep(PurePosixPath(".ENV")) is True
    # Unrelated defaults still apply.
    assert policy.keep(PurePosixPath(".venv/lib/x.py")) is False


def test_include_overrides_excludes_as_final_override() -> None:
    policy = BundlePolicy(
        exclude_lines=("logs/",),
        include_lines=("logs/keep.md",),
    )
    assert policy.keep(PurePosixPath("logs/keep.md")) is True
    assert policy.keep(PurePosixPath("logs/drop.md")) is False


def test_include_restores_env_case_insensitively() -> None:
    policy = BundlePolicy(include_lines=(".env",))
    assert policy.keep(PurePosixPath(".env")) is True
    assert policy.keep(PurePosixPath(".ENV")) is True
    assert policy.keep(PurePosixPath("nested/.Env")) is True


def test_included_separates_explicit_include_from_mere_non_exclusion() -> None:
    policy = BundlePolicy(exclude_lines=("logs/",), include_lines=(".env",))
    assert policy.included(PurePosixPath(".env")) is True
    assert policy.included(PurePosixPath(".ENV")) is True
    # A kept-but-not-included path must not be offered to the include rescue.
    assert policy.included(PurePosixPath("SKILL.md")) is False
    assert policy.included(PurePosixPath("logs/keep.md")) is False


def test_load_bundle_policy_without_files_uses_defaults() -> None:
    policy = load_bundle_policy(FakeSource({}))
    assert policy.keep(PurePosixPath(".env")) is False
    assert policy.keep(PurePosixPath("SKILL.md")) is True


def test_load_bundle_policy_reads_both_files() -> None:
    source = FakeSource(
        {
            GITIGNORE_PATH.as_posix(): b"# comment\n\nlogs/\n!.env\n",
            INCLUDE_PATH.as_posix(): b"include:\n  - .env\n",
        }
    )
    policy = load_bundle_policy(source)
    assert policy.keep(PurePosixPath("logs/a.md")) is False
    assert policy.keep(PurePosixPath(".env")) is True


def test_load_bundle_policy_rejects_invalid_yaml() -> None:
    source = FakeSource({INCLUDE_PATH.as_posix(): b"include: [unclosed\n"})
    with pytest.raises(CatalogError, match="invalid YAML"):
        load_bundle_policy(source)


def test_load_bundle_policy_rejects_unknown_keys() -> None:
    source = FakeSource({INCLUDE_PATH.as_posix(): b"include: []\nextra: []\n"})
    with pytest.raises(CatalogError, match="unknown keys: extra"):
        load_bundle_policy(source)


def test_load_bundle_policy_rejects_unsafe_patterns() -> None:
    absolute = FakeSource({INCLUDE_PATH.as_posix(): b"include:\n  - /etc/passwd\n"})
    with pytest.raises(CatalogError, match="unsafe"):
        load_bundle_policy(absolute)
    parent = FakeSource({GITIGNORE_PATH.as_posix(): b"../secret\n"})
    with pytest.raises(CatalogError, match="unsafe"):
        load_bundle_policy(parent)


def test_load_bundle_policy_propagates_read_failure() -> None:
    """An existing but unreadable file must not be mistaken for an absent one."""

    class FlakySource(FakeSource):
        def read_file(self, path: PurePosixPath) -> bytes:
            raise SourceError("network failure")

    source = FlakySource({GITIGNORE_PATH.as_posix(): b"logs/\n"})
    with pytest.raises(SourceError, match="network failure"):
        load_bundle_policy(source)
