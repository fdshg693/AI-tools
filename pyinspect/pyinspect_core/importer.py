"""Optional isolated import: ephemeral venv, public names only, then delete."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pyinspect_core.config import IMPORT_TIMEOUT_SECONDS

# Importing a third-party wheel can run arbitrary code (sitecustomize, C
# extensions, import-time side effects). Cap the wait so a hang cannot pin
# the CLI. 60s is long enough for a single no-deps import of a typical
# library and short enough for an interactive agent call.
_IMPORT_SCRIPT = (
    "import importlib, json, sys\n"
    "mod = importlib.import_module(sys.argv[1])\n"
    "declared = getattr(mod, '__all__', None)\n"
    "if declared is not None:\n"
    "    names = [str(n) for n in declared]\n"
    "else:\n"
    "    names = sorted(n for n in dir(mod) if not n.startswith('_'))\n"
    "print(json.dumps(names, ensure_ascii=False))\n"
)


@dataclass(frozen=True)
class ImportResult:
    ok: bool
    module: str | None
    names: list[str]
    reason: str


def infer_modules(tree_root: Path) -> list[str]:
    """``*.dist-info/top_level.txt``, then top-level packages. Deterministic order."""
    names: list[str] = []
    if tree_root.is_dir():
        for top_level in sorted(tree_root.glob("*.dist-info/top_level.txt")):
            for line in top_level.read_text(encoding="utf-8", errors="replace").splitlines():
                item = line.strip()
                if item and not item.startswith("#") and item not in names:
                    names.append(item)
    if names:
        return names

    if tree_root.is_dir():
        for path in sorted(tree_root.iterdir()):
            if not path.is_dir():
                continue
            if path.name.endswith(".dist-info") or path.name.endswith(".data"):
                continue
            if (path / "__init__.py").is_file() and path.name not in names:
                names.append(path.name)
    return names


def resolve_module(tree_root: Path, module: str | None) -> tuple[str | None, str]:
    """Return ``(module, error)``. Error is set when inference is ambiguous."""
    if module:
        return module, ""
    inferred = infer_modules(tree_root)
    if len(inferred) == 1:
        return inferred[0], ""
    if not inferred:
        return None, "could not infer an import name; pass --module"
    listed = ", ".join(inferred)
    return None, f"multiple import names ({listed}); pass --module"


def _venv_python(venv: Path) -> Path:
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _find_uv() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv was not found on PATH; required for --import")
    return uv


def run_isolated_import(
    wheel_path: Path,
    module: str,
    *,
    timeout: int = IMPORT_TIMEOUT_SECONDS,
) -> ImportResult:
    """Install ``wheel_path`` only (``--no-deps --no-index``) and list public names."""
    uv = _find_uv()
    tmp = Path(tempfile.mkdtemp(prefix="pyinspect-venv-"))
    try:
        created = subprocess.run(
            [uv, "venv", str(tmp)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if created.returncode != 0:
            detail = (
                created.stderr or created.stdout or ""
            ).strip() or f"exit {created.returncode}"
            return ImportResult(False, module, [], f"uv venv failed: {detail}")

        python = _venv_python(tmp)
        installed = subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                "--no-index",
                str(wheel_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if installed.returncode != 0:
            detail = (
                installed.stderr or installed.stdout or ""
            ).strip() or f"exit {installed.returncode}"
            return ImportResult(False, module, [], f"uv pip install failed: {detail}")

        imported = subprocess.run(
            [str(python), "-c", _IMPORT_SCRIPT, module],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if imported.returncode != 0:
            detail = (
                imported.stderr or imported.stdout or ""
            ).strip() or f"exit {imported.returncode}"
            return ImportResult(False, module, [], f"import {module!r} failed: {detail}")
        try:
            names = json.loads(imported.stdout)
        except json.JSONDecodeError as exc:
            return ImportResult(False, module, [], f"import output was not JSON: {exc}")
        if not isinstance(names, list):
            return ImportResult(False, module, [], "import output was not a list")
        return ImportResult(True, module, [str(n) for n in names], "")
    except subprocess.TimeoutExpired:
        return ImportResult(False, module, [], f"import timed out after {timeout}s")
    except OSError as exc:
        return ImportResult(False, module, [], f"import runner failed: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def format_import_lines(result: ImportResult) -> list[str]:
    if result.ok:
        names = ", ".join(result.names) if result.names else "(none)"
        return [
            f"- Module: {result.module}",
            f"- Public names: {names}",
        ]
    return [
        f"- Failed: {result.reason}",
    ]
