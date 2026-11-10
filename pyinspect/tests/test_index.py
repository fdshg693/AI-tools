from __future__ import annotations

from pathlib import Path

from pyinspect_core.index import (
    extract_wheel,
    format_file_tree,
    recommended_paths,
    render_index,
    upsert_import_section,
)
from pyinspect_core.pypi import ProjectRelease
from wheel_fixtures import build_wheel_bytes, wheel_filename, write_wheel


def _release() -> ProjectRelease:
    return ProjectRelease(
        name="demo",
        version="1.0.0",
        summary="A demo",
        requires_python=">=3.8",
        requires_dist=["packaging"],
        home_page="https://example.com",
        yanked=False,
        yanked_reason=None,
        wheels=[],
        raw_info={},
    )


def test_extract_and_recommended_paths(tmp_path: Path) -> None:
    content = build_wheel_bytes()
    wheel = write_wheel(tmp_path, content, wheel_filename())
    tree = tmp_path / "tree"
    extract_wheel(wheel, tree)
    (tree / "demo" / "py.typed").write_text("partial\n", encoding="utf-8")
    rec = recommended_paths(tree, tmp_path)
    assert "tree/README.md" in rec
    assert "tree/demo/py.typed" in rec
    assert "tree/demo/__init__.py" in rec
    assert any(p.endswith(".dist-info/METADATA") for p in rec)
    assert len(rec) <= 8


def _pkg(tree: Path, name: str, *, typed: str | None = None) -> None:
    pkg = tree / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    if typed is not None:
        (pkg / "py.typed").write_text(typed, encoding="utf-8")


def test_recommended_prefers_regular_package_over_underscore(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    _pkg(tree, "_yaml")
    _pkg(tree, "yaml")
    rec = recommended_paths(tree, tmp_path)
    assert "tree/yaml/__init__.py" in rec
    assert "tree/_yaml/__init__.py" not in rec


def test_recommended_falls_back_to_underscore_when_no_regular(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    _pkg(tree, "_yaml")
    rec = recommended_paths(tree, tmp_path)
    assert rec == ["tree/_yaml/__init__.py"]


def test_recommended_skips_empty_py_typed(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    _pkg(tree, "bs4", typed="")
    rec = recommended_paths(tree, tmp_path)
    assert "tree/bs4/py.typed" not in rec
    assert "tree/bs4/__init__.py" in rec


def test_recommended_keeps_nonempty_py_typed(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    _pkg(tree, "demo", typed="partial\n")
    rec = recommended_paths(tree, tmp_path)
    assert rec[0] == "tree/demo/py.typed"
    assert "tree/demo/__init__.py" in rec


def test_recommended_includes_multiple_regular_inits(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    _pkg(tree, "alpha")
    _pkg(tree, "beta")
    rec = recommended_paths(tree, tmp_path)
    assert "tree/alpha/__init__.py" in rec
    assert "tree/beta/__init__.py" in rec


def test_recommended_reserves_slot_for_metadata(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    for i in range(8):
        _pkg(tree, f"pkg{i}")
    meta = tree / "demo-1.0.0.dist-info"
    meta.mkdir()
    (meta / "METADATA").write_text("Name: demo\n", encoding="utf-8")
    rec = recommended_paths(tree, tmp_path)
    assert any(p.endswith(".dist-info/METADATA") for p in rec)
    inits = [p for p in rec if p.endswith("__init__.py")]
    assert len(inits) == 7
    assert len(rec) == 8


def test_file_tree_truncates() -> None:
    entries = [(f"tree/f{i}.py", i) for i in range(5)]
    lines = format_file_tree(entries, limit=3)
    assert len(lines) == 4
    assert "showing 3 of 5" in lines[-1]


def test_render_index_has_required_sections() -> None:
    text = render_index(
        _release(),
        state="fetched",
        reason="downloaded demo-1.0.0-py3-none-any.whl (12 bytes)",
        tree_lines=["- tree/demo/__init__.py (10 bytes)"],
        recommended=["tree/demo/__init__.py"],
    )
    assert "## Metadata" in text
    assert "## Status" in text
    assert "## File tree" in text
    assert "## Recommended paths" in text
    assert "## Import" not in text
    assert "Requires-Dist:" in text
    assert "packaging" in text


def test_upsert_import_replaces_old_section() -> None:
    base = render_index(
        _release(),
        state="fetched",
        reason="ok",
        tree_lines=["- (none)"],
        recommended=[],
        import_lines=["- Failed: pass --module"],
    )
    updated = upsert_import_section(base, ["- Module: demo", "- Public names: VALUE"])
    assert updated.count("## Import") == 1
    assert "Failed:" not in updated
    assert "Public names: VALUE" in updated
