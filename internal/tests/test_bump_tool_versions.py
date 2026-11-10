from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "release" / "bump_tool_versions.py"


def load_module():
    spec = importlib.util.spec_from_file_location("bump_tool_versions_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_pyproject(path: Path, version: str) -> None:
    path.write_text(
        textwrap.dedent(
            f"""
            [project]
            name = "{path.parent.name}"
            version = "{version}"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def write_package_json(path: Path, version: str | None) -> None:
    payload: dict[str, object] = {"name": path.parent.name, "private": True}
    if version is not None:
        payload["version"] = version
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def bump_patch(version: str) -> str:
    pieces = version.split(".")
    pieces[-1] = str(int(pieces[-1]) + 1)
    return ".".join(pieces)


def test_resolve_manifest_supports_python_and_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = load_module()
    repo = tmp_path
    (repo / "repo-tools.yaml").write_text(
        textwrap.dedent(
            """
            tools:
              py-tool:
                path: tools/py-tool
                install: uv tool install --editable tools/py-tool
              node-tool:
                path: tools/node-tool
                install: cd tools/node-tool && pnpm add -g .
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "tools" / "py-tool").mkdir(parents=True)
    (repo / "tools" / "node-tool").mkdir(parents=True)
    write_pyproject(repo / "tools" / "py-tool" / "pyproject.toml", "1.2.3")
    write_package_json(repo / "tools" / "node-tool" / "package.json", "2.3.4")

    monkeypatch.setattr(module, "REPO_ROOT", repo)
    monkeypatch.setattr(module, "REPO_TOOLS_YAML_PATH", repo / "repo-tools.yaml")

    tools = module.load_registered_tools()
    py_manifest = module.resolve_manifest(tools[0])
    node_manifest = module.resolve_manifest(tools[1])

    assert py_manifest.kind == "python"
    assert py_manifest.version == "1.2.3"
    assert py_manifest.manifest_rel_posix == "tools/py-tool/pyproject.toml"
    assert node_manifest.kind == "node"
    assert node_manifest.version == "2.3.4"
    assert node_manifest.manifest_rel_posix == "tools/node-tool/package.json"


def test_resolve_manifest_rejects_missing_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = load_module()
    repo = tmp_path
    (repo / "repo-tools.yaml").write_text(
        textwrap.dedent(
            """
            tools:
              linear-cli:
                path: tools/linear-cli
                install: cd tools/linear-cli && pnpm add -g .
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "tools" / "linear-cli").mkdir(parents=True)
    write_package_json(repo / "tools" / "linear-cli" / "package.json", None)

    monkeypatch.setattr(module, "REPO_ROOT", repo)
    monkeypatch.setattr(module, "REPO_TOOLS_YAML_PATH", repo / "repo-tools.yaml")

    with pytest.raises(module.ToolVersionError, match="package.json has no version"):
        module.resolve_manifest(module.load_registered_tools()[0])


def test_run_bumps_python_and_node_once_and_stages_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    module = load_module()
    repo = tmp_path
    (repo / "repo-tools.yaml").write_text(
        textwrap.dedent(
            """
            tools:
              aim:
                path: tools/aim
                install: uv tool install --editable tools/aim
              aim2:
                path: tools/aim2
                install: cd tools/aim2 && pnpm add -g .
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "tools" / "aim").mkdir(parents=True)
    (repo / "tools" / "aim2").mkdir(parents=True)
    pyproject = repo / "tools" / "aim" / "pyproject.toml"
    package_json = repo / "tools" / "aim2" / "package.json"
    write_pyproject(pyproject, "0.1.0")
    write_package_json(package_json, "0.2.0")
    head_files = {
        "tools/aim/pyproject.toml": pyproject.read_text(encoding="utf-8"),
        "tools/aim2/package.json": package_json.read_text(encoding="utf-8"),
    }
    staged: list[str] = []

    monkeypatch.setattr(module, "REPO_ROOT", repo)
    monkeypatch.setattr(module, "REPO_TOOLS_YAML_PATH", repo / "repo-tools.yaml")

    def fake_run(command, cwd=None, capture_output=False, text=False, errors=None, check=False):
        del capture_output, text, errors, check
        if command[:2] == ["git", "show"]:
            rel_path = command[2].split(":", 1)[1]
            content = head_files.get(rel_path)
            if content is None:
                return subprocess.CompletedProcess(command, 128, "", "missing")
            return subprocess.CompletedProcess(command, 0, content, "")
        if command[:3] == ["uv", "version", "--bump"]:
            write_pyproject(
                pyproject,
                bump_patch(module.parse_pyproject_version(pyproject.read_text(encoding="utf-8"))),
            )
            return subprocess.CompletedProcess(command, 0, "bumped python", "")
        if command[:3] == ["pnpm", "version", "patch"]:
            write_package_json(
                package_json,
                bump_patch(
                    module.parse_package_json_version(package_json.read_text(encoding="utf-8"))
                ),
            )
            return subprocess.CompletedProcess(command, 0, "bumped node", "")
        if command[:2] == ["git", "add"]:
            staged.append(command[-1])
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"unexpected command: {command!r} cwd={cwd!r}")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert (
        module.run(
            ["tools/aim/README.md", "tools/aim2/src/cli.ts", "tools/not-registered/foo.txt"],
            dry_run=False,
        )
        == 0
    )

    assert module.parse_pyproject_version(pyproject.read_text(encoding="utf-8")) == "0.1.1"
    assert module.parse_package_json_version(package_json.read_text(encoding="utf-8")) == "0.2.1"
    assert staged == ["tools/aim/pyproject.toml", "tools/aim2/package.json"]
    out = capsys.readouterr().out
    assert "tools/aim: bumped python" in out
    assert "tools/aim2: bumped node" in out


def test_run_skips_when_manifest_version_already_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    module = load_module()
    repo = tmp_path
    (repo / "repo-tools.yaml").write_text(
        textwrap.dedent(
            """
            tools:
              aim:
                path: tools/aim
                install: uv tool install --editable tools/aim
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "tools" / "aim").mkdir(parents=True)
    pyproject = repo / "tools" / "aim" / "pyproject.toml"
    write_pyproject(pyproject, "0.2.0")
    head_files = {
        "tools/aim/pyproject.toml": textwrap.dedent(
            """
            [project]
            name = "aim"
            version = "0.1.9"
            """
        ).strip()
        + "\n"
    }

    monkeypatch.setattr(module, "REPO_ROOT", repo)
    monkeypatch.setattr(module, "REPO_TOOLS_YAML_PATH", repo / "repo-tools.yaml")

    def fake_run(command, cwd=None, capture_output=False, text=False, errors=None, check=False):
        del cwd, capture_output, text, errors, check
        if command[:2] == ["git", "show"]:
            rel_path = command[2].split(":", 1)[1]
            return subprocess.CompletedProcess(command, 0, head_files[rel_path], "")
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.run(["tools/aim/README.md"], dry_run=False) == 0
    assert module.parse_pyproject_version(pyproject.read_text(encoding="utf-8")) == "0.2.0"
    assert capsys.readouterr().out.strip() == "No registered tool manifests needed a version bump."


def test_main_supports_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    module = load_module()
    repo = tmp_path
    (repo / "repo-tools.yaml").write_text(
        textwrap.dedent(
            """
            tools:
              icw:
                path: tools/interactive-cli-wrapper
                install: uv tool install --editable tools/interactive-cli-wrapper
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    tool_dir = repo / "tools" / "interactive-cli-wrapper"
    tool_dir.mkdir(parents=True)
    manifest = tool_dir / "pyproject.toml"
    write_pyproject(manifest, "1.0.0")

    monkeypatch.setattr(module, "REPO_ROOT", repo)
    monkeypatch.setattr(module, "REPO_TOOLS_YAML_PATH", repo / "repo-tools.yaml")

    def fake_run(command, cwd=None, capture_output=False, text=False, errors=None, check=False):
        del cwd, capture_output, text, errors, check
        if command[:2] == ["git", "show"]:
            rel_path = command[2].split(":", 1)[1]
            assert rel_path == "tools/interactive-cli-wrapper/pyproject.toml"
            return subprocess.CompletedProcess(command, 0, manifest.read_text(encoding="utf-8"), "")
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.main(["--dry-run", "tools/interactive-cli-wrapper/README.md"]) == 0
    assert "would bump tools/interactive-cli-wrapper/pyproject.toml" in capsys.readouterr().out
