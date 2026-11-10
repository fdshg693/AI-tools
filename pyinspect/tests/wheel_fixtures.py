"""Minimal in-memory / on-disk wheels and a fake ``requests`` session."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any


def build_wheel_bytes(
    *,
    name: str = "demo",
    version: str = "1.0.0",
    modules: list[str] | None = None,
    tag: str = "py3-none-any",
    extra_files: dict[str, str] | None = None,
) -> bytes:
    modules = modules or [name.replace("-", "_")]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for module in modules:
            zf.writestr(f"{module}/__init__.py", "VALUE = 1\n__all__ = ['VALUE']\n")
            zf.writestr(f"{module}/py.typed", "")
        zf.writestr("README.md", f"# {name}\n")
        dist = f"{name}-{version}.dist-info"
        zf.writestr(
            f"{dist}/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nSummary: A demo\n",
        )
        zf.writestr(f"{dist}/top_level.txt", "\n".join(modules) + "\n")
        zf.writestr(
            f"{dist}/WHEEL",
            f"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: {tag}\n",
        )
        for rel, content in (extra_files or {}).items():
            zf.writestr(rel, content)
    return buf.getvalue()


def wheel_filename(name: str = "demo", version: str = "1.0.0", tag: str = "py3-none-any") -> str:
    return f"{name}-{version}-{tag}.whl"


def project_payload(
    *,
    name: str = "demo",
    version: str = "1.0.0",
    wheel: bytes | None = None,
    filename: str | None = None,
    size: int | None = None,
    extra_urls: list[dict[str, Any]] | None = None,
    yanked: bool = False,
    yanked_reason: str | None = None,
    summary: str = "A demo",
    requires_python: str = ">=3.8",
    requires_dist: list[str] | None = None,
    home_page: str = "https://example.com",
) -> dict[str, Any]:
    filename = filename or wheel_filename(name, version)
    url = f"https://files.example.test/{filename}"
    sha256 = hashlib.sha256(wheel).hexdigest() if wheel is not None else "0" * 64
    if size is None:
        size = len(wheel) if wheel is not None else 100
    urls: list[dict[str, Any]] = [
        {
            "packagetype": "bdist_wheel",
            "filename": filename,
            "size": size,
            "url": url,
            "yanked": False,
            "requires_python": requires_python,
            "digests": {"sha256": sha256},
        }
    ]
    if extra_urls:
        urls.extend(extra_urls)
    return {
        "info": {
            "name": name,
            "version": version,
            "summary": summary,
            "requires_python": requires_python,
            "requires_dist": requires_dist or [],
            "home_page": home_page,
            "yanked": yanked,
            "yanked_reason": yanked_reason,
        },
        "urls": urls,
    }


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        json_data: Any = None,
        content: bytes = b"",
        text: str | None = None,
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.text = text if text is not None else content.decode("utf-8", errors="replace")
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json

    def iter_content(self, chunk_size: int = 65536):
        if not self.content:
            return
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i : i + chunk_size]


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.routes: dict[str, FakeResponse] = {}

    def get(self, url: str, **_kwargs) -> FakeResponse:
        self.calls.append(url)
        if url in self.routes:
            return self.routes[url]
        return FakeResponse(status_code=404, json_data={"message": "Not Found"})

    def add_json(self, url: str, payload: dict[str, Any], status_code: int = 200) -> None:
        self.routes[url] = FakeResponse(status_code=status_code, json_data=payload)

    def add_bytes(self, url: str, content: bytes, status_code: int = 200) -> None:
        self.routes[url] = FakeResponse(status_code=status_code, content=content)


def write_wheel(directory: Path, content: bytes, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(content)
    return path


def json_url(name: str, version: str | None = None) -> str:
    if version:
        return f"https://pypi.org/pypi/{name}/{version}/json"
    return f"https://pypi.org/pypi/{name}/json"
