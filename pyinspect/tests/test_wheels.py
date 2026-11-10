from __future__ import annotations

from packaging.tags import Tag

from pyinspect_core.pypi import WheelFile, select_import_wheel, select_read_wheel


def _w(filename: str, size: int, *, yanked: bool = False) -> WheelFile:
    return WheelFile(
        filename=filename,
        url=f"https://files.example.test/{filename}",
        size=size,
        sha256="",
        yanked=yanked,
        requires_python=None,
    )


def test_read_prefers_py3_none_any() -> None:
    manylinux = _w("demo-1.0.0-cp313-cp313-manylinux_2_17_x86_64.whl", 10)
    pure = _w("demo-1.0.0-py3-none-any.whl", 999)
    win = _w("demo-1.0.0-cp313-cp313-win_amd64.whl", 20)
    chosen = select_read_wheel([manylinux, pure, win], allow_yanked=False)
    assert chosen is not None
    assert chosen.filename.endswith("py3-none-any.whl")


def test_read_prefers_matching_tag_over_smaller_foreign(monkeypatch) -> None:
    matching = _w("demo-1.0.0-cp313-cp313-win_amd64.whl", 80)
    smaller = _w("demo-1.0.0-cp313-cp313-win32.whl", 10)
    monkeypatch.setattr(
        "pyinspect_core.pypi.sys_tags",
        lambda: (Tag("cp313", "cp313", "win_amd64"),),
    )
    chosen = select_read_wheel([matching, smaller], allow_yanked=False)
    assert chosen is not None
    assert chosen.filename == matching.filename


def test_read_falls_back_to_size_when_no_tag_matches(monkeypatch) -> None:
    bigger = _w("demo-1.0.0-cp313-cp313-manylinux_2_17_x86_64.whl", 80)
    smaller = _w("demo-1.0.0-cp313-cp313-macosx_11_0_arm64.whl", 40)
    monkeypatch.setattr("pyinspect_core.pypi.sys_tags", lambda: ())
    chosen = select_read_wheel([bigger, smaller], allow_yanked=False)
    assert chosen is not None
    assert chosen.filename == smaller.filename


def test_read_skips_yanked_unless_pinned() -> None:
    yanked = _w("demo-1.0.0-py3-none-any.whl", 10, yanked=True)
    assert select_read_wheel([yanked], allow_yanked=False) is None
    assert select_read_wheel([yanked], allow_yanked=True) is yanked


def test_import_requires_compatible_tag() -> None:
    foreign = _w("demo-1.0.0-cp313-cp313-manylinux_2_17_x86_64.whl", 10)
    pure = _w("demo-1.0.0-py3-none-any.whl", 50)
    chosen = select_import_wheel([foreign, pure], allow_yanked=False)
    assert chosen is not None
    assert chosen.filename.endswith("py3-none-any.whl")
