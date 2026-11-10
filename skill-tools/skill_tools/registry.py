"""Locate a source's SSOT yaml files (``ai-tools.yaml``, ``repo-tools.yaml`` ...).

The source repository keeps them under ``registry/``. Sources that predate that
layout (or other repositories following the old one) keep them at the root, so
``registry/<name>`` is preferred and the root file is the fallback. Paths written
inside these files stay repository-root relative either way.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from .source import CatalogSource

REGISTRY_DIR = PurePosixPath("registry")


def registry_file(source: CatalogSource, filename: str) -> PurePosixPath:
    """Return ``registry/<filename>`` when the source has it, else ``<filename>``."""

    preferred = REGISTRY_DIR / filename
    if source.list_files((preferred,)):
        return preferred
    return PurePosixPath(filename)
