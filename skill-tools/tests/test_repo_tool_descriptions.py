from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from skill_tools.repo_tools.descriptions import resolve_description
from skill_tools.models import CatalogError
from skill_tools.repo_tools import RepoTool, parse_locator
from skill_tools.source import LocalSource


def make_source(tmp_path: Path, files: dict[str, str]) -> LocalSource:
    root = tmp_path / "source"
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return LocalSource(root)


def tool_with(locator: str | None, key: str = "demo") -> RepoTool:
    return RepoTool(
        key=key,
        path=PurePosixPath("tools/demo"),
        install="install demo",
        description=None if locator is None else parse_locator(locator, key),
    )


def test_resolve_description_is_empty_without_a_locator(tmp_path: Path) -> None:
    source = make_source(tmp_path, {"README.md": "# demo\n"})
    assert resolve_description(tool_with(None), source) == ""


@pytest.mark.parametrize(
    ("filename", "content", "key", "expected"),
    [
        (
            "pyproject.toml",
            '[project]\nname = "demo"\ndescription = "TOML summary"\n',
            "project.description",
            "TOML summary",
        ),
        ("package.json", '{"description": "JSON summary"}\n', "description", "JSON summary"),
        ("meta.yaml", "description: YAML summary\n", "description", "YAML summary"),
        (
            "nested.yml",
            "project:\n  meta:\n    description: Nested summary\n",
            "project.meta.description",
            "Nested summary",
        ),
    ],
)
def test_resolve_description_reads_structured_keys(
    tmp_path: Path, filename: str, content: str, key: str, expected: str
) -> None:
    source = make_source(tmp_path, {filename: content})
    assert resolve_description(tool_with(f"{filename}#{key}"), source) == expected


def test_resolve_description_walks_list_indexes(tmp_path: Path) -> None:
    source = make_source(tmp_path, {"meta.json": '{"items": [{"name": "Summary"}]}\n'})
    assert resolve_description(tool_with("meta.json#items.0.name"), source) == "Summary"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("# demo — a summary\n\nbody\n", "demo — a summary"),
        ("---\nname: demo\n---\n\n# demo summary\n", "demo summary"),
        ("first non-empty line\n\nsecond\n", "first non-empty line"),
        ("\n\n> quoted summary\n", "quoted summary"),
        ("intro line\n\n# real heading\n", "real heading"),
    ],
)
def test_resolve_description_reads_plain_text(tmp_path: Path, content: str, expected: str) -> None:
    source = make_source(tmp_path, {"README.md": content})
    assert resolve_description(tool_with("README.md"), source) == expected


@pytest.mark.parametrize(
    ("locator", "files", "match"),
    [
        (
            "pyproject.toml#project.description",
            {"pyproject.toml": "[project]\ndescription = 3\n"},
            "non-empty string",
        ),
        ("package.json#missing", {"package.json": '{"a": 1}\n'}, "was not found"),
        ("meta.yaml#description", {"meta.yaml": "description:\n"}, "non-empty string"),
        (
            "pyproject.toml",
            {"pyproject.toml": '[project]\ndescription = "x"\n'},
            "#key",
        ),
        ("README.md#title", {"README.md": "# title\n"}, "#key"),
        ("notes.txt", {"notes.txt": "\n\n"}, "no summary line"),
        ("missing.md", {"README.md": "# x\n"}, "could not be read"),
    ],
)
def test_resolve_description_rejects_broken_locators(
    tmp_path: Path, locator: str, files: dict[str, str], match: str
) -> None:
    source = make_source(tmp_path, files)
    with pytest.raises(CatalogError, match=match):
        resolve_description(tool_with(locator), source)
