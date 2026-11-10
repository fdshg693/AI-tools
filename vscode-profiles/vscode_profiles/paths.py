from __future__ import annotations

import os
import platform
from pathlib import Path

from vscode_profiles.errors import CliError


def default_user_data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        if "APPDATA" not in os.environ:
            raise CliError("APPDATA is not set")
        appdata = os.environ["APPDATA"]
        if appdata == "":
            raise CliError("APPDATA is empty")
        return Path(appdata) / "Code"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Code"
    return Path.home() / ".config" / "Code"


def resolve_user_data_dir(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    return default_user_data_dir()
