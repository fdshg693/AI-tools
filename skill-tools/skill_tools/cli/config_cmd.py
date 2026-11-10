"""Config show and init commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ..config import FB_DIR_ENV, initialize_user_config, source_identity
from ..index.build import read_index
from ..locations import package_dir, pyproject_path, readme_path
from ..models import IndexError
from .arguments import (
    _add_runtime_arguments,
    _configured_source_description,
    _index_matches_configured_source,
    _load_runtime_config,
)


def _add_config_command(commands) -> None:
    config_command = commands.add_parser("config", help="inspect the resolved configuration")
    config_commands = config_command.add_subparsers(dest="config_command", required=True)
    show = config_commands.add_parser(
        "show", help="show the selected config, source, and index path"
    )
    _add_runtime_arguments(show)
    init = config_commands.add_parser(
        "init", help="create the global config file with explicit default values"
    )
    init.add_argument("--force", action="store_true", help="replace an existing global config")


def _command_config_show(args: argparse.Namespace, cwd: Path) -> int:
    config = _load_runtime_config(args, cwd)
    identity = source_identity(config)
    print(f"config: {config.config_path if config.config_path else '(defaults)'}")
    if config.global_config_path is not None:
        state = "found" if config.global_config_exists else "missing; using embedded defaults"
        print(f"config.global: {config.global_config_path} ({state})")
        print(f"config.cwd: {config.cwd_config_path}")
    print(f"source.type: {identity['type']}")
    if identity["type"] == "local":
        print(f"source.path: {identity['path']}")
    else:
        print(f"source.owner: {identity['owner']}")
        print(f"source.repository: {identity['repository']}")
        print(f"source.ref: {identity['ref']}")
    print(f"index.path: {config.index.path}")
    print(f"fb.path: {config.fb.path}")
    override = os.environ.get(FB_DIR_ENV, "").strip()
    if override:
        print(f"fb.path: {Path(override).expanduser().resolve()} ({FB_DIR_ENV})")
    print(f"self_skill: {config.self_skill}")
    # Never recompute the fingerprint here: for a local source it hashes every
    # visible file. Only echo the value an index matching this source stored.
    fingerprint = None
    commit = None
    try:
        index = read_index(config.index.path)
        if _index_matches_configured_source(index, config):
            fingerprint = dict(index["source"]["fingerprint"])
            commit = index["source"]["descriptor"].get("commit")
        else:
            print("index.source: mismatch")
    except IndexError:
        print("index: missing")
    if fingerprint is not None:
        print(f"source.fingerprint: {json.dumps(fingerprint, ensure_ascii=False, sort_keys=True)}")
    if commit:
        print(f"resolved.commit: {commit}")
    pyproject = pyproject_path()
    if pyproject is not None:
        print(f"package.pyproject: {pyproject}")
        readme = readme_path()
        if readme is not None:
            print(f"package.readme: {readme}")
    else:
        print("package.pyproject: (not shipped with this install)")
        print(f"package.dir: {package_dir()}")
    print(f"source: {_configured_source_description(config)}", file=sys.stderr)
    if config.global_config_path is not None and not config.global_config_exists:
        print(
            f"warning: global config is missing at {config.global_config_path}; "
            "embedded defaults are in use (run `skill-tools config init`)",
            file=sys.stderr,
        )
    return 0


def _command_config_init(args: argparse.Namespace) -> int:
    path, created = initialize_user_config(force=args.force)
    if created:
        print(f"Created global config: {path}")
    else:
        print(f"Global config already exists: {path}")
    return 0
