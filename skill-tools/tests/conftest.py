from __future__ import annotations

import json
from pathlib import Path

import pytest

CATALOG = """\
tools:
  claude-code:
    plugins:
      - path: plugins/one
        kind: plugin
        skills_layout: subdir
  cursor:
    plugins:
      - path: plugins/two
        kind: plugin
        skills_layout: direct
"""

REPO_TOOLS = """\
tools:
  alpha-tool:
    path: tools/alpha-tool
    install: "uv tool install --editable tools/alpha-tool"
    release: true
    description: tools/alpha-tool/pyproject.toml#project.description
  beta-tool:
    path: tools/beta-tool
    install: "uv tool install --editable tools/beta-tool"
  gamma-tool:
    path: tools/gamma-tool
    install: "uv tool install --editable tools/gamma-tool"
    release: false
    description: tools/gamma-tool/pyproject.toml#project.description
"""


HOOK_CATALOG_DIR = "hooks/generated"

HOOK_CATALOG = {
    "schemaVersion": 1,
    "generatedBy": "fixture",
    "hooks": [
        {
            "id": "nested_rules",
            "description": "Inject nested rules",
            "distributable": True,
            "requiresTools": [],
            "agents": {
                "claude": {
                    "runner": "python",
                    "main": "nested_rules.py",
                    "files": [{"path": "claude/nested_rules.py", "installPath": "nested_rules.py"}],
                    "seedFiles": [],
                    "dependencies": [],
                    "registrations": [
                        {"event": "PreToolUse", "matcher": "Read"},
                        {"event": "CwdChanged"},
                    ],
                },
                "kilo": {
                    "runner": "python",
                    "main": "nested_rules.ts",
                    "files": [
                        {"path": "kilo/nested_rules.py", "installPath": "nested_rules.py"},
                        {"path": "kilo/nested_rules.ts", "installPath": "nested_rules.ts"},
                    ],
                    "seedFiles": [],
                    "dependencies": [],
                    "registrations": [],
                },
            },
        },
        {
            "id": "repo_only",
            "description": "Needs this repository",
            "distributable": False,
            "requiresTools": ["aim"],
            "agents": {
                "claude": {
                    "runner": "uv-script",
                    "main": "repo_only.py",
                    "files": [{"path": "claude/repo_only.py", "installPath": "repo_only.py"}],
                    "seedFiles": [
                        {
                            "path": "claude/seed/repo_only/config/repo_only.yaml",
                            "installPath": "config/repo_only.yaml",
                        }
                    ],
                    "dependencies": ["pyyaml"],
                    "registrations": [{"event": "Stop", "timeout": 10}],
                }
            },
        },
    ],
}


def write_hook_repo(root: Path, catalog: dict | None = None) -> Path:
    """Write repo-hooks.yaml, the catalog, and every file it references under ``root``."""

    catalog = HOOK_CATALOG if catalog is None else catalog
    root.mkdir(parents=True, exist_ok=True)
    (root / "repo-hooks.yaml").write_text(
        f"version: 1\ncatalog: {HOOK_CATALOG_DIR}/catalog.json\n", encoding="utf-8"
    )
    generated = root / HOOK_CATALOG_DIR
    generated.mkdir(parents=True, exist_ok=True)
    (generated / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    for hook in catalog["hooks"]:
        for agent in hook["agents"].values():
            for item in (*agent["files"], *agent["seedFiles"]):
                target = generated / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# fixture\n", encoding="utf-8")
    return root


def skill_document(name: str) -> bytes:
    return f"---\nname: {name}\ndescription: Description for {name}\n---\n\n# {name}\n".encode()


def make_repository(root: Path) -> Path:
    root.mkdir()
    (root / "ai-tools.yaml").write_text(CATALOG, encoding="utf-8")
    (root / "repo-tools.yaml").write_text(REPO_TOOLS, encoding="utf-8")
    tool_summaries = {
        "alpha-tool": "Alpha tool summary",
        "beta-tool": "Beta tool summary",
        "gamma-tool": "Gamma tool summary",
    }
    for tool, summary in tool_summaries.items():
        tool_dir = root / "tools" / tool
        tool_dir.mkdir(parents=True)
        (tool_dir / "pyproject.toml").write_text(
            f'[project]\nname = "{tool}"\nversion = "0.1.0"\ndescription = "{summary}"\n',
            encoding="utf-8",
        )
    alpha = root / "plugins" / "one" / "skills" / "alpha"
    alpha.mkdir(parents=True)
    (alpha / "SKILL.md").write_bytes(skill_document("alpha"))
    (alpha / "references").mkdir()
    (alpha / "references" / "guide.md").write_text("alpha guide\n", encoding="utf-8")
    beta = root / "plugins" / "two" / "beta"
    beta.mkdir(parents=True)
    (beta / "SKILL.md").write_bytes(skill_document("beta"))
    (root / "meta-plugins" / "skills" / "private").mkdir(parents=True)
    (root / "meta-plugins" / "skills" / "private" / "SKILL.md").write_bytes(skill_document("private"))
    return root


def write_local_config(path: Path, source: Path, index: Path) -> Path:
    path.write_text(
        "source:\n"
        "  type: local\n"
        f"  path: {source.as_posix()}\n"
        "index:\n"
        f"  path: {index.as_posix()}\n",
        encoding="utf-8",
    )
    return path


def make_unit_vector(first: float) -> list[float]:
    values = [0.0] * 1536
    values[0] = first
    return values


@pytest.fixture(autouse=True)
def isolated_run_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILL_TOOLS_LOG_DIR", str(tmp_path / "run-logs"))


@pytest.fixture
def make_repo():
    return make_repository


@pytest.fixture
def make_hook_repo():
    return write_hook_repo


@pytest.fixture
def hook_catalog() -> dict:
    return HOOK_CATALOG


@pytest.fixture
def write_config():
    return write_local_config


@pytest.fixture
def unit_vector():
    return make_unit_vector


@pytest.fixture
def embedder(unit_vector):
    def _embedder(texts):
        return [unit_vector(1.0) for _ in texts]

    return _embedder
