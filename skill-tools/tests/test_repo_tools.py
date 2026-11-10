from __future__ import annotations

from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from skill_tools.models import CatalogError, InstallError
from skill_tools.repo_tools import (
    DescriptionLocator,
    install_repo_tools,
    load_repo_tools,
    parse_locator,
    parse_repo_tools,
    resolve_install_root,
    select_repo_tools,
)
from skill_tools.source import LocalSource

VALID = """\
tools:
  aim:
    path: tools/aim
    install: "uv tool install --editable tools/aim"
    release: true
  my-agents:
    path: tools/my-agents
    install: "uv tool install --editable tools/my-agents"
    requires_tools:
      mslearn: library
"""


def test_parse_repo_tools_reads_path_install_and_release() -> None:
    import yaml

    tools = parse_repo_tools(yaml.safe_load(VALID))
    assert [tool.key for tool in tools] == ["aim", "my-agents"]
    assert tools[0].path == PurePosixPath("tools/aim")
    assert tools[0].install == "uv tool install --editable tools/aim"
    assert tools[0].release is True
    assert tools[1].release is False
    assert not hasattr(tools[1], "requires_tools")


def test_parse_repo_tools_accepts_but_ignores_requires_tools() -> None:
    """Intra-repo deps live in pyproject.toml/workspace, not in this installer."""

    import yaml

    for value in ("{mslearn: library}", "[not, a, mapping]"):
        tools = parse_repo_tools(
            yaml.safe_load(
                "tools:\n  aim:\n    path: tools/aim\n    install: x\n"
                f"    requires_tools: {value}\n"
            )
        )
        assert tools[0].key == "aim"


@pytest.mark.parametrize(
    "text",
    [
        "tools: []\n",
        "tools:\n  aim:\n    install: x\n",
        "tools:\n  aim:\n    path: /absolute\n    install: x\n",
        "tools:\n  aim:\n    path: ../outside\n    install: x\n",
        "tools:\n  aim:\n    path: tools/aim\n",
        "tools:\n  aim:\n    path: tools/aim\n    install: x\n    release: sometimes\n",
        "tools:\n  aim:\n    path: tools/aim\n    install: x\n    unknown: y\n",
        "tools:\n  aim:\n    path: tools/aim\n    install: x\n    description: /absolute\n",
    ],
)
def test_parse_repo_tools_rejects_invalid_entries(text: str) -> None:
    import yaml

    with pytest.raises(CatalogError):
        parse_repo_tools(yaml.safe_load(text))


def test_parse_repo_tools_reads_a_description_locator() -> None:
    import yaml

    tools = parse_repo_tools(
        yaml.safe_load(
            "tools:\n"
            "  aim:\n    path: tools/aim\n    install: x\n"
            "    description: tools/aim/pyproject.toml#project.description\n"
            "  tav:\n    path: tools/tav-cli\n    install: y\n"
            "    description: tools/tav-cli/README.md\n"
        )
    )
    assert tools[0].description == DescriptionLocator(
        path=PurePosixPath("tools/aim/pyproject.toml"), key="project.description"
    )
    assert tools[1].description == DescriptionLocator(path=PurePosixPath("tools/tav-cli/README.md"))


def test_parse_repo_tools_defaults_description_to_none() -> None:
    import yaml

    tools = parse_repo_tools(
        yaml.safe_load("tools:\n  aim:\n    path: tools/aim\n    install: x\n")
    )
    assert tools[0].description is None


@pytest.mark.parametrize(
    "locator",
    ["", "#", "#project.description", "tools/aim/README.md#", "/abs/README.md", "../x.md"],
)
def test_parse_locator_rejects_invalid_values(locator: str) -> None:
    with pytest.raises(CatalogError):
        parse_locator(locator, "aim")


@pytest.mark.parametrize("value", [None, 3, ["tools/aim"], {"path": "x"}])
def test_parse_locator_rejects_non_strings(value: object) -> None:
    with pytest.raises(CatalogError):
        parse_locator(value, "aim")


def test_load_repo_tools_validates_description_paths(tmp_path: Path) -> None:
    root = tmp_path / "source"
    (root / "tools" / "aim").mkdir(parents=True)
    (root / "tools" / "aim" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (root / "repo-tools.yaml").write_text(
        "tools:\n"
        "  aim:\n"
        "    path: tools/aim\n"
        "    install: x\n"
        "    description: tools/aim/missing.md\n",
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="description does not exist"):
        load_repo_tools(LocalSource(root))

    (root / "tools" / "aim" / "README.md").write_text("# aim\n", encoding="utf-8")
    (root / "repo-tools.yaml").write_text(
        "tools:\n"
        "  aim:\n"
        "    path: tools/aim\n"
        "    install: x\n"
        "    description: tools/aim/README.md\n",
        encoding="utf-8",
    )
    tools = load_repo_tools(LocalSource(root))
    assert tools[0].description == DescriptionLocator(path=PurePosixPath("tools/aim/README.md"))


def test_load_repo_tools_validates_registered_paths(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "repo-tools.yaml").write_text(
        "tools:\n  aim:\n    path: tools/aim\n    install: x\n", encoding="utf-8"
    )
    with pytest.raises(CatalogError, match="does not exist"):
        load_repo_tools(LocalSource(root))

    (root / "tools" / "aim").mkdir(parents=True)
    (root / "tools" / "aim" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    assert [tool.key for tool in load_repo_tools(LocalSource(root))] == ["aim"]


def test_select_repo_tools_accepts_names_paths_and_empty_means_all() -> None:
    import yaml

    catalog = parse_repo_tools(
        yaml.safe_load(
            "tools:\n"
            "  aim:\n    path: tools/aim\n    install: x\n"
            "  tav:\n    path: tools/tav-cli\n    install: y\n"
        )
    )
    assert select_repo_tools(catalog, []) == catalog
    assert [tool.key for tool in select_repo_tools(catalog, ["tav"])] == ["tav"]
    assert [tool.key for tool in select_repo_tools(catalog, ["tools/aim"])] == ["aim"]
    with pytest.raises(CatalogError, match="not found"):
        select_repo_tools(catalog, ["missing"])


def test_install_repo_tools_runs_in_root_and_stops_at_first_failure(tmp_path: Path) -> None:
    import yaml

    catalog = parse_repo_tools(
        yaml.safe_load(
            "tools:\n"
            "  first:\n    path: tools/first\n    install: run first\n"
            "  second:\n    path: tools/second\n    install: run second\n"
        )
    )
    calls: list[tuple[object, object, object]] = []

    def runner(command, cwd, shell, check):
        calls.append((command, cwd, shell))
        return SimpleNamespace(returncode=0 if command == "run first" else 7)

    root = tmp_path / "root"
    with pytest.raises(InstallError, match="second.*exit 7"):
        install_repo_tools(catalog, root, runner=runner)
    assert calls == [
        ("run first", root, True),
        ("run second", root, True),
    ]

    assert install_repo_tools(catalog[:1], root, runner=runner) == catalog[:1]


def test_resolve_install_root_requires_a_local_source(tmp_path: Path) -> None:
    root = tmp_path / "clone"
    root.mkdir()
    assert resolve_install_root(LocalSource(root)) == root.resolve()

    class Remote:
        pass

    with pytest.raises(InstallError, match="local source"):
        resolve_install_root(Remote())  # type: ignore[arg-type]
