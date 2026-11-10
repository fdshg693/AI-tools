"""Shared CLI arguments, runtime config, and source labels."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..config import apply_cli_overrides, load_config, source_identity
from ..source import GitHubSource


def _add_runtime_arguments(parser: argparse.ArgumentParser, *, index_path: bool = True) -> None:
    parser.add_argument("--config", type=Path, help="path to skill-tools.yaml")
    parser.add_argument(
        "--source",
        choices=("local", "github"),
        default=None,
        help="override the configured skill catalog source",
    )
    parser.add_argument("--repo", type=Path, help="local repository clone (with --source local)")
    parser.add_argument(
        "--github-owner",
        default=None,
        help="GitHub owner override",
    )
    parser.add_argument(
        "--github-repo",
        dest="github_repository",
        default=None,
        help="GitHub repository override",
    )
    parser.add_argument(
        "--github-ref",
        default=None,
        help="GitHub ref override",
    )
    if index_path:
        parser.add_argument("--index-path", type=Path, help="override the CLI index path")


def _load_runtime_config(args: argparse.Namespace, cwd: Path):
    config = load_config(config_path=getattr(args, "config", None), cwd=cwd)
    return apply_cli_overrides(
        config,
        source_type=getattr(args, "source", None),
        repo=getattr(args, "repo", None),
        github_owner=getattr(args, "github_owner", None),
        github_repository=getattr(args, "github_repository", None),
        github_ref=getattr(args, "github_ref", None),
        index_path=getattr(args, "index_path", None),
        cwd=cwd,
    )


def _source_description(source) -> str:
    if isinstance(source, GitHubSource):
        return f"github {source.owner}/{source.repository}@{source.commit_sha}"
    return f"local {source.root}"


def _configured_source_description(config) -> str:
    identity = source_identity(config)
    if identity["type"] == "local":
        return f"local {identity['path']}"
    return f"github {identity['owner']}/{identity['repository']}@{identity['ref']}"


def _index_matches_configured_source(index: Mapping[str, Any], config) -> bool:
    descriptor = index["source"]["descriptor"]
    identity = source_identity(config)
    return all(descriptor.get(key) == value for key, value in identity.items())


def _entry_matches_source(entry: Mapping[str, Any], source, cwd: Path) -> bool:
    recorded = entry["source"]
    current = dict(source.descriptor)
    if recorded.get("type") != current.get("type"):
        return False
    keys = (
        ("type", "path")
        if current.get("type") == "local"
        else (
            "type",
            "owner",
            "repository",
            "ref",
        )
    )
    for key in keys:
        old, new = recorded.get(key), current.get(key)
        if key == "path":
            old_path = Path(old).expanduser()
            if not old_path.is_absolute():
                old_path = cwd / old_path
            new_path = Path(new).expanduser()
            if old_path.resolve() != new_path.resolve():
                return False
        elif old != new:
            return False
    return True
