"""Specifier parsing, PyPI JSON, wheel selection, and wheel HTTP GET."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from packaging.specifiers import SpecifierSet
from packaging.tags import sys_tags
from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from packaging.version import InvalidVersion, Version

from pyinspect_core.config import DEFAULT_HTTP_TIMEOUT, PYPI_JSON_BASE
from pyinspect_core.environment import user_agent

_PEP503_SEP = re.compile(r"[-_.]+")
_SPEC_SPLIT = re.compile(r"^(.+?)==(.+)$")


class PyInspectError(Exception):
    """Base error with a process exit code."""

    exit_code = 1


class UsageError(PyInspectError):
    exit_code = 2


class NotFoundError(PyInspectError):
    exit_code = 3


class RuntimeRequestError(PyInspectError):
    exit_code = 1


@dataclass(frozen=True)
class Specifier:
    name: str
    version: str | None
    pinned: bool


@dataclass(frozen=True)
class WheelFile:
    filename: str
    url: str
    size: int
    sha256: str
    yanked: bool
    requires_python: str | None


@dataclass(frozen=True)
class ProjectRelease:
    name: str
    version: str
    summary: str
    requires_python: str | None
    requires_dist: list[str]
    home_page: str
    yanked: bool
    yanked_reason: str | None
    wheels: list[WheelFile]
    raw_info: dict[str, Any]


def normalize_name(name: str) -> str:
    """PEP 503 normalized distribution name."""
    return _PEP503_SEP.sub("-", name).lower()


def parse_specifier(raw: str) -> Specifier:
    """Accept ``name`` or ``name==version`` only. extras / URL / ranges are errors."""
    text = (raw or "").strip()
    if not text:
        raise UsageError("specifier is empty")
    if "[" in text or "]" in text:
        raise UsageError("extras are not supported; pass a PyPI name and optional ==version")
    if "://" in text or text.startswith("git+") or "@" in text:
        raise UsageError(
            "URL / VCS specifiers are not supported; pass a PyPI name and optional ==version"
        )

    match = _SPEC_SPLIT.match(text)
    if match:
        name = match.group(1).strip()
        version = match.group(2).strip()
        if not name or not version:
            raise UsageError("specifier must be NAME or NAME==VERSION")
        if any(op in version for op in (" ", ",", ">", "<", "!", "~")):
            raise UsageError("version ranges are not supported; pin with NAME==VERSION")
        try:
            Version(version)
        except InvalidVersion as exc:
            raise UsageError(f"invalid version {version!r}") from exc
        return Specifier(name=name, version=version, pinned=True)

    if "==" in text:
        raise UsageError("specifier must be NAME or NAME==VERSION")
    if any(op in text for op in (">", "<", "!", "~", ";")):
        raise UsageError("version ranges are not supported; pin with NAME==VERSION")
    return Specifier(name=text, version=None, pinned=False)


def _headers() -> dict[str, str]:
    return {"User-Agent": user_agent(), "Accept": "application/json"}


def fetch_project_json(
    spec: Specifier,
    *,
    session: requests.Session | None = None,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> dict[str, Any]:
    """GET ``/pypi/<name>/json`` or ``/pypi/<name>/<version>/json``."""
    name = quote(spec.name, safe="-_.")
    if spec.pinned:
        url = f"{PYPI_JSON_BASE}/{name}/{quote(spec.version or '', safe='+.')}/json"
    else:
        url = f"{PYPI_JSON_BASE}/{name}/json"

    getter = session.get if session is not None else requests.get
    try:
        response = getter(url, headers=_headers(), timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeRequestError(f"PyPI JSON request failed: {exc}") from exc

    if response.status_code == 404:
        target = f"{spec.name}=={spec.version}" if spec.pinned else spec.name
        raise NotFoundError(f"package or version not found on PyPI: {target}")
    if response.status_code >= 400:
        raise RuntimeRequestError(f"PyPI JSON HTTP {response.status_code} for {url}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeRequestError(f"PyPI JSON was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeRequestError("PyPI JSON root was not an object")
    return payload


def parse_release(payload: dict[str, Any]) -> ProjectRelease:
    info = payload.get("info")
    if not isinstance(info, dict):
        raise RuntimeRequestError("PyPI JSON missing info object")

    name = str(info.get("name") or "").strip()
    version = str(info.get("version") or "").strip()
    if not name or not version:
        raise RuntimeRequestError("PyPI JSON info missing name or version")

    requires_dist = info.get("requires_dist") or []
    if not isinstance(requires_dist, list):
        requires_dist = []
    dist_items = [str(item) for item in requires_dist if item]

    home = str(info.get("home_page") or "").strip()
    if not home:
        urls = info.get("project_urls") or {}
        if isinstance(urls, dict):
            for key in ("Homepage", "Home", "home", "Source"):
                candidate = urls.get(key)
                if candidate:
                    home = str(candidate).strip()
                    break

    yanked = bool(info.get("yanked"))
    yanked_reason = info.get("yanked_reason")
    if yanked_reason is not None:
        yanked_reason = str(yanked_reason)

    wheels: list[WheelFile] = []
    for entry in payload.get("urls") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("packagetype") != "bdist_wheel":
            continue
        filename = str(entry.get("filename") or "")
        url = str(entry.get("url") or "")
        if not filename or not url:
            continue
        try:
            size = int(entry.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        digests = entry.get("digests") or {}
        sha256 = ""
        if isinstance(digests, dict):
            sha256 = str(digests.get("sha256") or "")
        wheels.append(
            WheelFile(
                filename=filename,
                url=url,
                size=size,
                sha256=sha256,
                yanked=bool(entry.get("yanked")),
                requires_python=(
                    str(entry["requires_python"]) if entry.get("requires_python") else None
                ),
            )
        )

    return ProjectRelease(
        name=name,
        version=version,
        summary=str(info.get("summary") or "").strip(),
        requires_python=(str(info["requires_python"]) if info.get("requires_python") else None),
        requires_dist=dist_items,
        home_page=home,
        yanked=yanked,
        yanked_reason=yanked_reason,
        wheels=wheels,
        raw_info=info,
    )


def _is_pure_py3(filename: str) -> bool:
    stem = filename[:-4] if filename.endswith(".whl") else filename
    return stem.endswith("py3-none-any") or stem.endswith("py2.py3-none-any")


def _python_compatible(requires_python: str | None) -> bool:
    if not requires_python:
        return True
    try:
        spec = SpecifierSet(requires_python)
        current = Version(".".join(map(str, sys.version_info[:3])))
    except Exception:
        return True
    return current in spec


def _matches_sys_tags(filename: str) -> bool:
    try:
        _name, _version, _build, tags = parse_wheel_filename(filename)
    except InvalidWheelFilename:
        return False
    return bool(set(tags) & set(sys_tags()))


def _read_rank(filename: str) -> int:
    if _is_pure_py3(filename):
        return 0
    if _matches_sys_tags(filename):
        return 1
    return 2


def select_read_wheel(wheels: list[WheelFile], *, allow_yanked: bool) -> WheelFile | None:
    """Prefer ``py3-none-any``, then current ``sys_tags``, then size / filename."""
    candidates = [w for w in wheels if allow_yanked or not w.yanked]
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda w: (_read_rank(w.filename), w.size, w.filename),
    )
    return ranked[0]


def select_import_wheel(wheels: list[WheelFile], *, allow_yanked: bool) -> WheelFile | None:
    """Current interpreter tags only. Tie-break: size, filename."""
    candidates = [
        w
        for w in wheels
        if (allow_yanked or not w.yanked)
        and _python_compatible(w.requires_python)
        and _matches_sys_tags(w.filename)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda w: (w.size, w.filename))[0]


def download_wheel(
    wheel: WheelFile,
    dest: Path,
    *,
    session: requests.Session | None = None,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> None:
    """GET ``wheel.url`` and verify size + sha256 against the JSON record."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    getter = session.get if session is not None else requests.get
    try:
        response = getter(
            wheel.url,
            headers={"User-Agent": user_agent()},
            timeout=timeout,
            stream=True,
        )
    except requests.RequestException as exc:
        raise RuntimeRequestError(f"wheel download failed: {exc}") from exc

    if response.status_code >= 400:
        raise RuntimeRequestError(
            f"wheel download HTTP {response.status_code} for {wheel.filename}"
        )

    digest = hashlib.sha256()
    written = 0
    try:
        with dest.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                fh.write(chunk)
                digest.update(chunk)
                written += len(chunk)
    except OSError as exc:
        raise RuntimeRequestError(f"failed to write wheel: {exc}") from exc

    if wheel.size and written != wheel.size:
        dest.unlink(missing_ok=True)
        raise RuntimeRequestError(
            f"downloaded size {written} != JSON size {wheel.size} for {wheel.filename}"
        )
    if wheel.sha256:
        actual = digest.hexdigest()
        if actual.lower() != wheel.sha256.lower():
            dest.unlink(missing_ok=True)
            raise RuntimeRequestError(f"sha256 mismatch for {wheel.filename}")


def dump_release_snapshot(release: ProjectRelease) -> str:
    """JSON snapshot stored next to index.md so a later --import can rebuild."""
    payload = {
        "name": release.name,
        "version": release.version,
        "summary": release.summary,
        "requires_python": release.requires_python,
        "requires_dist": release.requires_dist,
        "home_page": release.home_page,
        "yanked": release.yanked,
        "yanked_reason": release.yanked_reason,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
