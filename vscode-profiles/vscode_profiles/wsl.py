from __future__ import annotations

import platform
import re
import subprocess
from pathlib import Path, PureWindowsPath

from vscode_profiles.errors import CliError
from vscode_profiles.profiles import Profile, machine_profile

_DISTRO = re.compile(r"^[A-Za-z0-9._-]+$")
MACHINE_SETTINGS = (".vscode-server", "data", "Machine", "settings.json")


def wsl_machine_profile(distro: str) -> Profile:
    """Pseudo profile for the VS Code Server Machine settings inside a WSL distribution."""
    if platform.system() != "Windows":
        raise CliError("--wsl is only available on Windows", code=2)
    if not _DISTRO.match(distro):
        raise CliError(f"invalid WSL distribution name: {distro!r}", code=2)
    return machine_profile(f"WSL:{distro}", machine_settings_path(distro, wsl_home(distro)))


def machine_settings_path(distro: str, home: str) -> Path:
    if not home.startswith("/"):
        raise CliError(f"unexpected HOME from WSL {distro!r}: {home!r}")
    root = PureWindowsPath(f"\\\\wsl.localhost\\{distro}\\")
    parts = [part for part in home.split("/") if part]
    return Path(root.joinpath(*parts, *MACHINE_SETTINGS))


def wsl_home(distro: str) -> str:
    try:
        completed = subprocess.run(
            ["wsl.exe", "-d", distro, "-e", "sh", "-c", 'printf %s "$HOME"'],
            capture_output=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CliError(f"could not run wsl.exe for {distro!r}: {exc}") from exc
    if completed.returncode != 0:
        raise CliError(f"wsl.exe failed for {distro!r} (exit {completed.returncode})")
    return completed.stdout.decode("utf-8", errors="replace").strip()
