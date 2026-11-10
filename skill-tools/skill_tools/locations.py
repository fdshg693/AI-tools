"""Resolve the skill-tools project directory from this file alone."""

from __future__ import annotations

import tomllib
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent


def project_root() -> Path:
    """Return the skill-tools project directory.

    A checkout or editable install keeps ``pyproject.toml`` next to the
    ``skill_tools`` package. An installed wheel does not, so return the
    directory that contains the package.
    """

    container = _PACKAGE_DIR.parent
    if (container / "pyproject.toml").is_file():
        return container
    return _PACKAGE_DIR.parent


def package_dir() -> Path:
    """Return the directory of the installed ``skill_tools`` package."""

    return _PACKAGE_DIR


def pyproject_path() -> Path | None:
    """Return this install's ``pyproject.toml``, or ``None`` when not shipped."""

    candidate = project_root() / "pyproject.toml"
    return candidate if candidate.is_file() else None


def readme_path() -> Path | None:
    """Resolve ``[project].readme`` of this install's ``pyproject.toml``.

    The path is relative to the directory holding ``pyproject.toml``. Returns
    ``None`` when there is no pyproject, no ``readme`` field, or it cannot be
    parsed.
    """

    pyproject = pyproject_path()
    if pyproject is None:
        return None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    readme = data.get("project", {}).get("readme")
    if isinstance(readme, dict):
        readme = readme.get("file")
    if not isinstance(readme, str) or not readme:
        return None
    return (pyproject.parent / readme).resolve()
