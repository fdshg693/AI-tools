"""Where install/manage commands place files, keep state, and look for skill-tools.yaml.

Only the CLI layer builds an ``InstallScope``. The lower layers (``installer``,
``manifest``, ``hooks.install``) keep taking a project root plus an optional
``state_dir`` keyword, so they stay independent of how the scope was chosen.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..config import global_state_dir
from ..models import ConfigError
from .manifest import MANIFEST_RELATIVE_PATH


@dataclass(frozen=True)
class InstallScope:
    """Placement root, managed-state directory, and config search directory."""

    kind: Literal["project", "global"]
    root: Path
    state_dir: Path
    config_dir: Path | None
    explicit: bool = False
    """True when the root came from ``--project-dir`` / ``--global`` rather than the CWD."""

    @classmethod
    def project(cls, root: Path, *, explicit: bool = False) -> InstallScope:
        resolved = root.resolve()
        return cls(
            kind="project",
            root=resolved,
            state_dir=resolved / MANIFEST_RELATIVE_PATH.parent,
            config_dir=resolved,
            explicit=explicit,
        )

    @classmethod
    def global_(cls) -> InstallScope:
        """User-wide scope: files under the home directory, state outside ``~/.skill-tools``.

        No project ``skill-tools.yaml`` is read, so the result does not depend
        on the directory the command runs from.
        """

        return cls(
            kind="global",
            root=Path.home().resolve(),
            state_dir=global_state_dir(),
            config_dir=None,
            explicit=True,
        )

    @property
    def is_global(self) -> bool:
        return self.kind == "global"

    def display(self, path: Path) -> str:
        """``~/<relative>`` for global installs, the root-relative POSIX path otherwise."""

        relative = path.relative_to(self.root).as_posix()
        return f"~/{relative}" if self.is_global else relative


def resolve_scope(args: argparse.Namespace, cwd: Path) -> InstallScope:
    """Resolve ``--global``, ``--project-dir`` (relative to the real CWD), or the CWD."""

    project_dir = getattr(args, "project_dir", None)
    if getattr(args, "global_scope", False):
        if project_dir is not None:
            raise ConfigError("--global and --project-dir cannot be used together")
        return InstallScope.global_()
    if project_dir is None:
        return InstallScope.project(cwd)
    path = Path(project_dir).expanduser()
    if not path.is_absolute():
        path = cwd / path
    if not path.is_dir():
        raise ConfigError(f"--project-dir must be an existing directory: {path}")
    return InstallScope.project(path, explicit=True)


def is_home_or_ancestor(root: Path) -> bool:
    home = Path.home().resolve()
    return home.is_relative_to(root.resolve())


def ensure_project_root_allowed(scope: InstallScope, command: str) -> None:
    """Refuse install/update into a project rooted at the home directory (or above it).

    A project rooted at home would manage the same files as ``--global`` from a
    second manifest. Listing and removal stay allowed so an existing home
    manifest can be cleaned up before reinstalling with ``--global``.
    """

    if scope.is_global or not is_home_or_ancestor(scope.root):
        return
    hooks = command.startswith("hooks ")
    kind, remove, install, item = (
        ("hooks", "hooks remove", "hooks install", "<hook>")
        if hooks
        else ("skills", "remove-skills", "install-skills", "<skill>")
    )
    raise ConfigError(
        f"{command}: the project root {scope.root} is the home directory or one of its "
        f"ancestors; use --global for user-wide installs. To move {kind} already managed "
        f"here: `skill-tools {remove}` in this directory, then "
        f"`skill-tools {install} --global {item}...`"
    )
