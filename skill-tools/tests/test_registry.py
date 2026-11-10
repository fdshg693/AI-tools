from pathlib import Path, PurePosixPath

from skill_tools.registry import registry_file
from skill_tools.repo_tools import load_repo_tools
from skill_tools.source import LocalSource

REPO_TOOLS = "version: 1\ntools:\n  {name}:\n    path: tools/{name}\n    install: echo {name}\n"


def _repo(root: Path, *, root_file: bool, registry_file_: bool) -> LocalSource:
    for name in ("alpha", "beta"):
        (root / "tools" / name).mkdir(parents=True)
        (root / "tools" / name / "README.md").write_text(name, encoding="utf-8")
    if root_file:
        (root / "repo-tools.yaml").write_text(REPO_TOOLS.format(name="alpha"), encoding="utf-8")
    if registry_file_:
        (root / "registry").mkdir()
        (root / "registry" / "repo-tools.yaml").write_text(
            REPO_TOOLS.format(name="beta"), encoding="utf-8"
        )
    return LocalSource(root)


def test_registry_dir_is_preferred_over_root(tmp_path: Path) -> None:
    source = _repo(tmp_path, root_file=True, registry_file_=True)
    assert registry_file(source, "repo-tools.yaml") == PurePosixPath("registry/repo-tools.yaml")
    assert [tool.key for tool in load_repo_tools(source)] == ["beta"]


def test_root_file_is_the_fallback(tmp_path: Path) -> None:
    source = _repo(tmp_path, root_file=True, registry_file_=False)
    assert registry_file(source, "repo-tools.yaml") == PurePosixPath("repo-tools.yaml")
    assert [tool.key for tool in load_repo_tools(source)] == ["alpha"]
