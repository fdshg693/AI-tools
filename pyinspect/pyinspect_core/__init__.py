"""Shared core for the ``pyinspect`` PyPI wheel index CLI."""

from __future__ import annotations

from pyinspect_core.config import (
    EXIT_IMPORT_FAILED,
    EXIT_METADATA_ONLY,
    EXIT_NOT_FOUND,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    EXIT_USAGE,
)
from pyinspect_core.inspect import InspectOutcome, run_inspect

__all__ = [
    "EXIT_IMPORT_FAILED",
    "EXIT_METADATA_ONLY",
    "EXIT_NOT_FOUND",
    "EXIT_RUNTIME_ERROR",
    "EXIT_SUCCESS",
    "EXIT_USAGE",
    "InspectOutcome",
    "run_inspect",
]
