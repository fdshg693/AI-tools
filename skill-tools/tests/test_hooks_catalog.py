from __future__ import annotations

import copy
from pathlib import Path, PurePosixPath

import pytest

from skill_tools.hooks.catalog import filter_hooks, load_hook_catalog, parse_hook_catalog
from skill_tools.models import CatalogError
from skill_tools.source import LocalSource

CATALOG_DIR = "hooks/generated"
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_loads_records_with_source_relative_paths(tmp_path: Path, make_hook_repo) -> None:
    hooks = load_hook_catalog(LocalSource(make_hook_repo(tmp_path / "repo")))

    assert [hook.id for hook in hooks] == ["nested_rules", "repo_only"]
    nested = hooks[0]
    assert [agent.agent for agent in nested.agents] == ["claude", "kilo"]
    kilo = nested.agent("kilo")
    assert kilo is not None and kilo.main == PurePosixPath("nested_rules.ts")
    assert kilo.files[1].source_path == PurePosixPath("hooks/generated/kilo/nested_rules.ts")
    assert nested.agent("claude").registrations[1] == {"event": "CwdChanged"}
    repo_only = hooks[1]
    assert repo_only.requires_tools == ("aim",)
    assert repo_only.agent("claude").seed_files[0].install_path == PurePosixPath(
        "config/repo_only.yaml"
    )
    assert PurePosixPath("hooks/generated/claude/seed/repo_only/config/repo_only.yaml") in (
        repo_only.files
    )


def test_source_without_repo_hooks_yaml_has_no_hooks(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("no hooks\n", encoding="utf-8")

    assert load_hook_catalog(LocalSource(root)) == ()


def test_filter_hides_private_hooks_and_selects_agents(tmp_path: Path, make_hook_repo) -> None:
    hooks = load_hook_catalog(LocalSource(make_hook_repo(tmp_path / "repo")))

    assert [hook.id for hook in filter_hooks(hooks)] == ["nested_rules"]
    assert [hook.id for hook in filter_hooks(hooks, include_private=True)] == [
        "nested_rules",
        "repo_only",
    ]
    assert filter_hooks(hooks, agent="codex") == ()
    assert [hook.id for hook in filter_hooks(hooks, agent="kilo")] == ["nested_rules"]
    with pytest.raises(CatalogError, match="unknown agent"):
        filter_hooks(hooks, agent="cline")


def test_missing_catalog_file_is_an_error(tmp_path: Path, make_hook_repo) -> None:
    root = make_hook_repo(tmp_path / "repo")
    (root / CATALOG_DIR / "catalog.json").unlink()

    with pytest.raises(CatalogError, match="unreadable"):
        load_hook_catalog(LocalSource(root))


def test_missing_generated_file_is_an_error(tmp_path: Path, make_hook_repo) -> None:
    root = make_hook_repo(tmp_path / "repo")
    (root / CATALOG_DIR / "kilo" / "nested_rules.ts").unlink()

    with pytest.raises(CatalogError, match="missing file: hooks/generated/kilo/nested_rules.ts"):
        load_hook_catalog(LocalSource(root))


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("version: 1\ncatalog: x.json\nextra: 1\n", "unknown keys: extra"),
        ("version: 2\ncatalog: x.json\n", "version must be 1"),
        ("version: 1\ncatalog: ../x.json\n", "unsafe"),
        ("version: [\n", "invalid YAML"),
    ],
)
def test_invalid_repo_hooks_yaml(
    tmp_path: Path, make_hook_repo, content: str, message: str
) -> None:
    root = make_hook_repo(tmp_path / "repo")
    (root / "repo-hooks.yaml").write_text(content, encoding="utf-8")

    with pytest.raises(CatalogError, match=message):
        load_hook_catalog(LocalSource(root))


def _claude(catalog: dict) -> dict:
    return catalog["hooks"][0]["agents"]["claude"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda c: c.update(schemaVersion=2), "unsupported schemaVersion"),
        (lambda c: c["hooks"][0].update(extra=True), "unknown keys: extra"),
        (lambda c: c["hooks"][0].pop("description"), "missing keys: description"),
        (lambda c: c["hooks"][0].update(id="Bad-Id"), "snake_case"),
        (lambda c: c["hooks"][0].update(distributable="yes"), "distributable must be a boolean"),
        (lambda c: c["hooks"][0]["agents"].update(cline={}), "unknown agents: cline"),
        (lambda c: _claude(c).update(runner="node"), "runner must be one of"),
        (lambda c: _claude(c).update(main="other.py"), "main must be one of"),
        (lambda c: _claude(c)["files"][0].update(path="../escape.py"), "unsafe"),
        (lambda c: _claude(c)["files"][0].update(installPath="C:/x.py"), "unsafe"),
        (lambda c: _claude(c).update(dependencies=["pyyaml"]), "only valid with runner uv-script"),
        (lambda c: _claude(c).update(registrations=[]), "must not be empty"),
        (lambda c: _claude(c)["registrations"][0].update(command="x"), "unknown keys: command"),
        (lambda c: _claude(c)["registrations"][0].pop("event"), "event is required"),
        (lambda c: _claude(c)["registrations"][0].update(matcher=""), "matcher must be"),
        (
            lambda c: c["hooks"][0]["agents"]["kilo"].update(registrations=[{"event": "x"}]),
            "must be empty for kilo",
        ),
        (lambda c: c["hooks"].append(copy.deepcopy(c["hooks"][0])), "duplicate hook ids"),
    ],
)
def test_catalog_validation_is_strict(hook_catalog: dict, mutate, message: str) -> None:
    catalog = copy.deepcopy(hook_catalog)
    mutate(catalog)
    with pytest.raises(CatalogError, match=message):
        parse_hook_catalog(catalog, PurePosixPath("hooks/generated/catalog.json"))


@pytest.mark.skipif(
    not (REPO_ROOT / "repo-hooks.yaml").is_file(), reason="not inside the ai repository"
)
def test_repository_catalog_satisfies_the_contract() -> None:
    """The committed agent-tooling catalog is what `skill-tools hooks` reads in practice."""

    hooks = load_hook_catalog(LocalSource(REPO_ROOT))

    by_id = {hook.id: hook for hook in hooks}
    assert "nested_agents_md" in by_id
    assert {agent.agent for agent in by_id["nested_agents_md"].agents} == {
        "claude",
        "codex",
        "cursor",
        "antigravity",
        "kilo",
    }
    assert any(not hook.distributable for hook in hooks)
