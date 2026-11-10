from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_TOOLS_PATH = REPO_ROOT / "repo-tools.yaml"


@dataclass(frozen=True)
class CommandCase:
    command: str
    version: str
    kind: str
    tool_dir: Path
    entry: str


def load_registered_cases() -> list[CommandCase]:
    config = yaml.safe_load(REPO_TOOLS_PATH.read_text(encoding="utf-8"))
    cases: list[CommandCase] = []
    for tool in config["tools"].values():
        tool_dir = REPO_ROOT / tool["path"]
        pyproject = tool_dir / "pyproject.toml"
        package_json = tool_dir / "package.json"
        if pyproject.is_file():
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            version = str(data["project"]["version"]).strip()
            for command, entry in data["project"]["scripts"].items():
                cases.append(
                    CommandCase(
                        command=command,
                        version=version,
                        kind="python",
                        tool_dir=tool_dir,
                        entry=entry,
                    )
                )
            continue
        if package_json.is_file():
            data = json.loads(package_json.read_text(encoding="utf-8"))
            version = str(data["version"]).strip()
            bins = data["bin"]
            if isinstance(bins, str):
                bins = {str(data["name"]): bins}
            for command, entry in bins.items():
                cases.append(
                    CommandCase(
                        command=command,
                        version=version,
                        kind="node",
                        tool_dir=tool_dir,
                        entry=str(entry),
                    )
                )
            continue
        raise AssertionError(f"no manifest found for registered tool: {tool['path']}")
    return cases


CASES = load_registered_cases()


def run_python_entrypoint(case: CommandCase) -> subprocess.CompletedProcess[str]:
    existing_path = os.environ.get("PYTHONPATH")
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{case.tool_dir}{os.pathsep}{existing_path}" if existing_path else str(case.tool_dir)
    )
    code = (
        "import importlib, inspect, sys; "
        "module_name, func_name = sys.argv[1].split(':', 1); "
        "sys.argv = ['cli', *sys.argv[2:]]; "
        "module = importlib.import_module(module_name); "
        "func = getattr(module, func_name); "
        "params = inspect.signature(func).parameters; "
        "result = func(sys.argv[1:]) if params else func(); "
        "raise SystemExit(0 if result is None else result)"
    )
    return subprocess.run(
        [sys.executable, "-c", code, case.entry, "--version"],
        cwd=case.tool_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def ensure_node_entrypoint(case: CommandCase) -> Path:
    entry_path = (case.tool_dir / case.entry).resolve()
    package_json = json.loads((case.tool_dir / "package.json").read_text(encoding="utf-8"))
    if "build" in package_json.get("scripts", {}):
        build = subprocess.run(
            ["pnpm", "build"],
            cwd=case.tool_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert build.returncode == 0, build.stderr or build.stdout
    elif entry_path.exists():
        return entry_path
    assert entry_path.exists(), f"node entrypoint was not created: {entry_path}"
    return entry_path


def run_node_entrypoint(case: CommandCase) -> subprocess.CompletedProcess[str]:
    entry_path = ensure_node_entrypoint(case)
    return subprocess.run(
        ["node", str(entry_path), "--version"],
        cwd=case.tool_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


@pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required for registered node CLIs"
)
@pytest.mark.skipif(
    shutil.which("pnpm") is None, reason="pnpm is required for registered node CLIs"
)
@pytest.mark.parametrize("case", CASES, ids=[case.command for case in CASES])
def test_registered_cli_version_contract(case: CommandCase):
    if case.kind == "python":
        result = run_python_entrypoint(case)
    else:
        result = run_node_entrypoint(case)

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stderr == ""
    assert result.stdout.splitlines() == [f"{case.command} {case.version}"]
