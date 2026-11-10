"""Update the installed skill-tools CLI itself from GitHub.

How this install was made is read from PEP 610 ``direct_url.json`` in the
distribution metadata, which pip and uv both write. An editable install
(``dir_info.editable``) tracks a local clone, so it is never replaced.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from .config import DEFAULT_GITHUB_OWNER, DEFAULT_GITHUB_REPOSITORY
from .models import InstallError

DISTRIBUTION_NAME = "skill-tools"
DEFAULT_URL = f"https://github.com/{DEFAULT_GITHUB_OWNER}/{DEFAULT_GITHUB_REPOSITORY}.git"
DEFAULT_SUBDIRECTORY = "tools/skill-tools"
WINDOWS_LOG_NAME = "skill-tools-update.log"


@dataclass(frozen=True)
class InstallOrigin:
    """Where the running skill-tools was installed from."""

    kind: str  # "editable" | "git" | "other"
    url: str | None = None
    revision: str | None = None
    subdirectory: str | None = None
    editable_path: str | None = None


def read_install_origin(
    distribution: metadata.Distribution | None = None,
) -> InstallOrigin:
    """Classify the install from ``direct_url.json`` (``other`` when it is absent)."""

    if distribution is None:
        try:
            distribution = metadata.distribution(DISTRIBUTION_NAME)
        except metadata.PackageNotFoundError as exc:
            raise InstallError(
                f"{DISTRIBUTION_NAME} is not installed as a package (running from source?); "
                "nothing to update"
            ) from exc
    raw = distribution.read_text("direct_url.json")
    if not raw:
        return InstallOrigin(kind="other")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return InstallOrigin(kind="other")
    if not isinstance(data, dict):
        return InstallOrigin(kind="other")
    url = data.get("url") if isinstance(data.get("url"), str) else None
    dir_info = data.get("dir_info")
    if isinstance(dir_info, dict) and dir_info.get("editable") is True:
        return InstallOrigin(kind="editable", editable_path=url)
    vcs_info = data.get("vcs_info")
    if isinstance(vcs_info, dict) and vcs_info.get("vcs") == "git" and url:
        revision = vcs_info.get("requested_revision")
        subdirectory = data.get("subdirectory")
        return InstallOrigin(
            kind="git",
            url=url,
            revision=revision if isinstance(revision, str) and revision else None,
            subdirectory=subdirectory if isinstance(subdirectory, str) and subdirectory else None,
        )
    return InstallOrigin(kind="other")


def requirement_spec(origin: InstallOrigin) -> str:
    """Return the ``git+...`` requirement that fetches the latest skill-tools.

    A previous git install keeps its repository, requested branch/tag, and
    subdirectory. Anything else falls back to the default GitHub repository.
    """

    if origin.kind == "git" and origin.url:
        url, revision, subdirectory = origin.url, origin.revision, origin.subdirectory
    else:
        url, revision, subdirectory = DEFAULT_URL, None, None
    spec = url if url.startswith("git+") else f"git+{url}"
    if revision:
        spec += f"@{revision}"
    return f"{spec}#subdirectory={subdirectory or DEFAULT_SUBDIRECTORY}"


def uv_tool_environment(prefix: str | None = None) -> bool:
    """Return whether this interpreter lives in a ``uv tool`` environment."""

    return (Path(prefix or sys.prefix) / "uv-receipt.toml").is_file()


def update_command(spec: str, uv: str = "uv") -> list[str]:
    return [uv, "tool", "install", "--force", spec]


def run_update(command: list[str]) -> str | None:
    """Run the update command; return a log path when it was left running.

    On Windows the running ``skill-tools.exe`` and its venv cannot be replaced
    by their own child process, so the command is started after this process
    exits. Elsewhere it runs in the foreground.
    """

    if os.name != "nt":
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise InstallError(f"`{' '.join(command)}` failed with exit code {result.returncode}")
        return None
    log_path = Path(tempfile.gettempdir()) / WINDOWS_LOG_NAME
    quoted = " ".join("'" + part.replace("'", "''") + "'" for part in command)
    script = f"Start-Sleep -Seconds 2; & {quoted}"
    try:
        with log_path.open("wb") as log:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
    except OSError as exc:
        raise InstallError(f"could not start the update: {exc}") from exc
    return str(log_path)


def locate_uv() -> str:
    uv = shutil.which("uv")
    if uv is None:
        raise InstallError("`uv` was not found on PATH; install uv to update skill-tools")
    return uv
