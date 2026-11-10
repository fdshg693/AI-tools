from __future__ import annotations

import hashlib
from pathlib import Path

from pyinspect_core.config import (
    EXIT_IMPORT_FAILED,
    EXIT_METADATA_ONLY,
    EXIT_SUCCESS,
)
from pyinspect_core.importer import ImportResult
from pyinspect_core.inspect import run_inspect
from pyinspect_core.pypi import NotFoundError, UsageError
from wheel_fixtures import (
    FakeSession,
    build_wheel_bytes,
    json_url,
    project_payload,
    wheel_filename,
)


def _session_for(
    *,
    name: str = "demo",
    version: str = "1.0.0",
    wheel: bytes | None = None,
    payload_kwargs: dict | None = None,
    pinned: bool = False,
) -> tuple[FakeSession, bytes]:
    content = wheel if wheel is not None else build_wheel_bytes(name=name, version=version)
    filename = wheel_filename(name, version)
    payload = project_payload(
        name=name, version=version, wheel=content, filename=filename, **(payload_kwargs or {})
    )
    session = FakeSession()
    session.add_json(json_url(name, version if pinned else None), payload)
    session.add_bytes(f"https://files.example.test/{filename}", content)
    return session, content


def _ok_importer(_wheel: Path, module: str) -> ImportResult:
    return ImportResult(True, module, ["VALUE"], "")


def test_over_size_writes_index_without_download(tmp_path: Path) -> None:
    session, _ = _session_for(payload_kwargs={"size": 99_000_000})
    outcome = run_inspect(
        "demo",
        output_dir=tmp_path,
        max_bytes=50,
        session=session,
    )
    assert outcome.exit_code == EXIT_METADATA_ONLY
    assert outcome.index_path is not None
    text = outcome.index_path.read_text(encoding="utf-8")
    assert "metadata-only:over-size" in text
    assert not (outcome.index_path.parent / "tree").exists()
    assert not any(u.startswith("https://files.example.test/") for u in session.calls)


def test_no_wheel_is_metadata_only(tmp_path: Path) -> None:
    payload = project_payload(wheel=b"unused")
    payload["urls"] = [
        {
            "packagetype": "sdist",
            "filename": "demo-1.0.0.tar.gz",
            "size": 10,
            "url": "https://files.example.test/demo-1.0.0.tar.gz",
            "yanked": False,
            "digests": {"sha256": "00"},
        }
    ]
    session = FakeSession()
    session.add_json(json_url("demo"), payload)
    outcome = run_inspect("demo", output_dir=tmp_path, session=session)
    assert outcome.exit_code == EXIT_METADATA_ONLY
    assert outcome.index_path is not None
    assert "metadata-only:no-wheel" in outcome.index_path.read_text(encoding="utf-8")


def test_yanked_latest_skips_fetch(tmp_path: Path) -> None:
    session, _ = _session_for(payload_kwargs={"yanked": True, "yanked_reason": "broken"})
    outcome = run_inspect("demo", output_dir=tmp_path, session=session)
    assert outcome.exit_code == EXIT_METADATA_ONLY
    text = outcome.index_path.read_text(encoding="utf-8")
    assert "metadata-only:yanked-latest" in text
    assert not any(u.startswith("https://files.example.test/") for u in session.calls)


def test_pinned_yanked_still_fetches(tmp_path: Path) -> None:
    session, _ = _session_for(pinned=True, payload_kwargs={"yanked": True, "yanked_reason": "oops"})
    outcome = run_inspect("demo==1.0.0", output_dir=tmp_path, session=session)
    assert outcome.exit_code == EXIT_SUCCESS
    text = outcome.index_path.read_text(encoding="utf-8")
    assert "Yanked: true" in text
    assert "fetched" in text


def test_cache_hit_skips_second_download(tmp_path: Path) -> None:
    session, _ = _session_for()
    first = run_inspect("demo", output_dir=tmp_path, session=session)
    assert first.exit_code == EXIT_SUCCESS
    downloads = [u for u in session.calls if u.startswith("https://files.example.test/")]
    assert len(downloads) == 1
    second = run_inspect("demo", output_dir=tmp_path, session=session)
    assert second.exit_code == EXIT_SUCCESS
    assert second.index_path == first.index_path
    downloads_after = [u for u in session.calls if u.startswith("https://files.example.test/")]
    assert downloads_after == downloads


def test_cache_hit_rewrites_index_without_download(tmp_path: Path) -> None:
    session, _ = _session_for()
    first = run_inspect("demo", output_dir=tmp_path, session=session)
    assert first.index_path is not None
    planted = first.index_path.read_text(encoding="utf-8").replace(
        "## Recommended paths\n\n",
        "## Recommended paths\n\n- tree/stale.py\n",
    )
    first.index_path.write_text(planted, encoding="utf-8")
    downloads = [u for u in session.calls if u.startswith("https://files.example.test/")]
    second = run_inspect("demo", output_dir=tmp_path, session=session)
    assert second.exit_code == EXIT_SUCCESS
    text = second.index_path.read_text(encoding="utf-8")
    assert "tree/stale.py" not in text
    assert "tree/demo/__init__.py" in text
    downloads_after = [u for u in session.calls if u.startswith("https://files.example.test/")]
    assert downloads_after == downloads


def test_cache_hit_refetches_when_read_wheel_differs(tmp_path: Path) -> None:
    win_tag = "cp313-cp313-win32"
    win_name = wheel_filename("demo", "1.0.0", win_tag)
    win_bytes = build_wheel_bytes(tag=win_tag, extra_files={"demo/from_win32.py": "x"})
    pure_name = wheel_filename("demo", "1.0.0")
    pure_bytes = build_wheel_bytes(extra_files={"demo/from_pure.py": "y"})

    session = FakeSession()
    session.add_json(json_url("demo"), project_payload(wheel=win_bytes, filename=win_name))
    session.add_bytes(f"https://files.example.test/{win_name}", win_bytes)

    first = run_inspect("demo", output_dir=tmp_path, session=session)
    assert first.exit_code == EXIT_SUCCESS
    assert first.index_path is not None
    assert (first.index_path.parent / "tree" / "demo" / "from_win32.py").is_file()

    session.add_json(
        json_url("demo"),
        project_payload(
            wheel=pure_bytes,
            filename=pure_name,
            extra_urls=[
                {
                    "packagetype": "bdist_wheel",
                    "filename": win_name,
                    "size": len(win_bytes),
                    "url": f"https://files.example.test/{win_name}",
                    "yanked": False,
                    "requires_python": ">=3.8",
                    "digests": {"sha256": hashlib.sha256(win_bytes).hexdigest()},
                }
            ],
        ),
    )
    session.add_bytes(f"https://files.example.test/{pure_name}", pure_bytes)

    second = run_inspect("demo", output_dir=tmp_path, session=session)
    assert second.exit_code == EXIT_SUCCESS
    assert second.index_path is not None
    cache = second.index_path.parent
    assert (cache / "tree" / "demo" / "from_pure.py").is_file()
    assert not (cache / "tree" / "demo" / "from_win32.py").is_file()
    downloads = [u for u in session.calls if u.startswith("https://files.example.test/")]
    assert f"https://files.example.test/{pure_name}" in downloads


def test_version_omitted_resolves_to_json_version(tmp_path: Path) -> None:
    session, _ = _session_for(version="9.9.9")
    outcome = run_inspect("demo", output_dir=tmp_path, session=session)
    assert outcome.exit_code == EXIT_SUCCESS
    assert outcome.index_path is not None
    assert "9.9.9" in str(outcome.index_path.as_posix())
    assert "# demo 9.9.9" in outcome.index_path.read_text(encoding="utf-8")


def test_later_import_skips_redownload(tmp_path: Path) -> None:
    session, _ = _session_for()
    first = run_inspect("demo", output_dir=tmp_path, session=session)
    assert first.exit_code == EXIT_SUCCESS
    downloads = [u for u in session.calls if u.startswith("https://files.example.test/")]
    second = run_inspect(
        "demo",
        do_import=True,
        output_dir=tmp_path,
        session=session,
        import_runner=_ok_importer,
    )
    assert second.exit_code == EXIT_SUCCESS
    text = second.index_path.read_text(encoding="utf-8")
    assert "## Import" in text
    assert "Public names: VALUE" in text
    downloads_after = [u for u in session.calls if u.startswith("https://files.example.test/")]
    assert downloads_after == downloads


def test_module_required_when_ambiguous(tmp_path: Path) -> None:
    content = build_wheel_bytes(modules=["alpha", "beta"])
    session, _ = _session_for(wheel=content)
    failed = run_inspect(
        "demo",
        do_import=True,
        output_dir=tmp_path,
        session=session,
        import_runner=_ok_importer,
    )
    assert failed.exit_code == EXIT_IMPORT_FAILED
    assert "pass --module" in failed.index_path.read_text(encoding="utf-8")

    ok = run_inspect(
        "demo",
        do_import=True,
        module="alpha",
        output_dir=tmp_path,
        session=session,
        import_runner=_ok_importer,
    )
    assert ok.exit_code == EXIT_SUCCESS
    assert "Module: alpha" in ok.index_path.read_text(encoding="utf-8")


def test_normalize_name_shares_cache(tmp_path: Path) -> None:
    content = build_wheel_bytes(name="Pillow", version="11.0.0")
    filename = wheel_filename("Pillow", "11.0.0")
    payload = project_payload(name="Pillow", version="11.0.0", wheel=content, filename=filename)
    session = FakeSession()
    session.add_json(json_url("Pillow"), payload)
    session.add_json(json_url("pillow"), payload)
    session.add_bytes(f"https://files.example.test/{filename}", content)

    first = run_inspect("Pillow", output_dir=tmp_path, session=session)
    second = run_inspect("pillow", output_dir=tmp_path, session=session)
    assert first.exit_code == EXIT_SUCCESS
    assert second.index_path == first.index_path
    assert "pillow/11.0.0" in first.index_path.as_posix()
    downloads = [u for u in session.calls if u.startswith("https://files.example.test/")]
    assert len(downloads) == 1


def test_incomplete_cache_is_redone(tmp_path: Path) -> None:
    session, _ = _session_for()
    first = run_inspect("demo", output_dir=tmp_path, session=session)
    cache = first.index_path.parent
    (cache / ".complete").unlink()
    leftover = cache / "tree" / "stale.txt"
    leftover.parent.mkdir(parents=True, exist_ok=True)
    leftover.write_text("stale", encoding="utf-8")

    second = run_inspect("demo", output_dir=tmp_path, session=session)
    assert second.exit_code == EXIT_SUCCESS
    assert not leftover.exists()


def test_over_size_cache_upgrades_when_cap_rises(tmp_path: Path) -> None:
    session, _ = _session_for()
    first = run_inspect("demo", output_dir=tmp_path, max_bytes=1, session=session)
    assert first.exit_code == EXIT_METADATA_ONLY
    second = run_inspect("demo", output_dir=tmp_path, max_bytes=50_000_000, session=session)
    assert second.exit_code == EXIT_SUCCESS
    assert (second.index_path.parent / "tree").is_dir()


def test_not_found_has_no_index() -> None:
    session = FakeSession()
    try:
        run_inspect("missing", output_dir=Path("unused"), session=session)
    except NotFoundError:
        return
    raise AssertionError("expected NotFoundError")


def test_module_without_import_is_usage(tmp_path: Path) -> None:
    session, _ = _session_for()
    try:
        run_inspect("demo", module="demo", output_dir=tmp_path, session=session)
    except UsageError:
        return
    raise AssertionError("expected UsageError")


def test_import_size_exceeded_skips_entity(tmp_path: Path) -> None:
    session, _ = _session_for(payload_kwargs={"size": 80})
    outcome = run_inspect(
        "demo",
        do_import=True,
        output_dir=tmp_path,
        max_bytes=50,
        session=session,
        import_runner=_ok_importer,
    )
    assert outcome.exit_code == EXIT_METADATA_ONLY
    assert not any(u.startswith("https://files.example.test/") for u in session.calls)
