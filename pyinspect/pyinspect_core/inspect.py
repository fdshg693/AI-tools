"""Orchestrate JSON lookup, cache, download, index, and optional import."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

from pyinspect_core.cache import (
    INDEX_NAME,
    LOCK_NAME,
    SNAPSHOT_NAME,
    TREE_DIRNAME,
    WHEELS_DIRNAME,
    CacheState,
    atomic_replace,
    cache_dir,
    exclusive_lock,
    is_complete,
    load_state,
    remove_incomplete,
    staging_dir,
    write_state,
)
from pyinspect_core.config import (
    EXIT_IMPORT_FAILED,
    EXIT_METADATA_ONLY,
    EXIT_SUCCESS,
)
from pyinspect_core.environment import get_max_bytes, get_output_dir
from pyinspect_core.importer import (
    ImportResult,
    format_import_lines,
    resolve_module,
    run_isolated_import,
)
from pyinspect_core.index import (
    extract_wheel,
    format_file_tree,
    iter_tree_entries,
    recommended_paths,
    render_index,
    upsert_import_section,
)
from pyinspect_core.pypi import (
    ProjectRelease,
    UsageError,
    WheelFile,
    download_wheel,
    dump_release_snapshot,
    fetch_project_json,
    parse_release,
    parse_specifier,
    select_import_wheel,
    select_read_wheel,
)

ImportRunner = Callable[[Path, str], ImportResult]


@dataclass(frozen=True)
class InspectOutcome:
    exit_code: int
    index_path: Path | None


def _default_import_runner(wheel_path: Path, module: str) -> ImportResult:
    return run_isolated_import(wheel_path, module)


def _decide(
    release: ProjectRelease,
    *,
    pinned: bool,
    do_import: bool,
    max_bytes: int,
) -> tuple[bool, str, str, WheelFile | None, WheelFile | None]:
    """Return ``(fetch, state, reason, read_wheel, import_wheel)``."""
    if not pinned and release.yanked:
        return (
            False,
            "metadata-only:yanked-latest",
            "latest version is yanked; not fetching a wheel",
            None,
            None,
        )

    read = select_read_wheel(release.wheels, allow_yanked=pinned)
    import_w = select_import_wheel(release.wheels, allow_yanked=pinned) if do_import else None

    if do_import and import_w is not None and import_w.size > max_bytes:
        return (
            False,
            "metadata-only:over-size",
            f"import wheel {import_w.filename} is {import_w.size} bytes (max {max_bytes})",
            read,
            import_w,
        )
    if read is None:
        return (
            False,
            "metadata-only:no-wheel",
            "no bdist_wheel on PyPI for this version",
            None,
            import_w,
        )
    if read.size > max_bytes:
        return (
            False,
            "metadata-only:over-size",
            f"wheel {read.filename} is {read.size} bytes (max {max_bytes})",
            read,
            import_w,
        )
    reason = f"downloaded {read.filename} ({read.size} bytes)"
    return True, "fetched", reason, read, import_w


def _release_from_snapshot(snapshot: Path, release: ProjectRelease) -> ProjectRelease:
    if not snapshot.is_file():
        return release
    try:
        data = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return release
    if not isinstance(data, dict):
        return release
    return ProjectRelease(
        name=str(data.get("name") or release.name),
        version=str(data.get("version") or release.version),
        summary=str(data.get("summary") or release.summary),
        requires_python=data.get("requires_python") or release.requires_python,
        requires_dist=list(data.get("requires_dist") or release.requires_dist),
        home_page=str(data.get("home_page") or release.home_page),
        yanked=bool(data.get("yanked")) if "yanked" in data else release.yanked,
        yanked_reason=data.get("yanked_reason", release.yanked_reason),
        wheels=release.wheels,
        raw_info=release.raw_info,
    )


def _import_lines_from_index(index_path: Path) -> list[str] | None:
    if not index_path.is_file():
        return None
    text = index_path.read_text(encoding="utf-8")
    marker = "## Import"
    idx = text.find(marker)
    if idx < 0:
        return None
    body = text[idx + len(marker) :].lstrip("\n")
    lines = [line for line in body.splitlines() if line.strip()]
    return lines or None


def _write_index_file(
    directory: Path,
    release: ProjectRelease,
    *,
    state: str,
    reason: str,
    import_lines: list[str] | None,
) -> None:
    tree_root = directory / TREE_DIRNAME
    entries = iter_tree_entries(tree_root, directory)
    text = render_index(
        release,
        state=state,
        reason=reason,
        tree_lines=format_file_tree(entries),
        recommended=recommended_paths(tree_root, directory),
        import_lines=import_lines,
    )
    (directory / INDEX_NAME).write_text(text, encoding="utf-8")


def _ensure_wheel(
    wheel: WheelFile,
    dest_dir: Path,
    *,
    session: requests.Session | None,
) -> Path:
    dest = dest_dir / wheel.filename
    if dest.is_file() and dest.stat().st_size == wheel.size:
        return dest
    download_wheel(wheel, dest, session=session)
    return dest


def _run_import(
    *,
    tree_root: Path,
    wheel_path: Path | None,
    module: str | None,
    runner: ImportRunner,
) -> ImportResult:
    chosen, error = resolve_module(tree_root, module)
    if error or not chosen:
        return ImportResult(
            False, chosen, [], error or "could not infer an import name; pass --module"
        )
    if wheel_path is None or not wheel_path.is_file():
        return ImportResult(
            False,
            chosen,
            [],
            "no wheel compatible with this interpreter for --import",
        )
    return runner(wheel_path, chosen)


def _apply_import(
    directory: Path,
    release: ProjectRelease,
    state: CacheState,
    result: ImportResult,
) -> None:
    import_lines = format_import_lines(result)
    index_path = directory / INDEX_NAME
    if index_path.is_file():
        updated = upsert_import_section(index_path.read_text(encoding="utf-8"), import_lines)
        index_path.write_text(updated, encoding="utf-8")
    else:
        _write_index_file(
            directory,
            release,
            state=state.status if state.status == "fetched" else state.reason,
            reason=state.reason,
            import_lines=import_lines,
        )
    state.import_done = True
    state.import_ok = result.ok
    write_state(directory, state)


def run_inspect(
    specifier: str,
    *,
    do_import: bool = False,
    module: str | None = None,
    output_dir: Path | None = None,
    max_bytes: int | None = None,
    session: requests.Session | None = None,
    import_runner: ImportRunner | None = None,
) -> InspectOutcome:
    if module and not do_import:
        raise UsageError("--module requires --import")

    spec = parse_specifier(specifier)
    payload = fetch_project_json(spec, session=session)
    release = parse_release(payload)

    root = output_dir if output_dir is not None else get_output_dir()
    limit = max_bytes if max_bytes is not None else get_max_bytes()
    runner = import_runner or _default_import_runner

    fetch, state_name, reason, read_wheel, import_wheel = _decide(
        release, pinned=spec.pinned, do_import=do_import, max_bytes=limit
    )

    final = cache_dir(root, release.name, release.version)
    lock_path = final.parent / LOCK_NAME

    with exclusive_lock(lock_path):
        remove_incomplete(final)
        existing = load_state(final) if is_complete(final) else None

        if existing is not None and existing.status == "fetched":
            selected_name = read_wheel.filename if fetch and read_wheel is not None else None
            if selected_name is None or existing.read_wheel == selected_name:
                index_path = final / INDEX_NAME
                snap_release = _release_from_snapshot(final / SNAPSHOT_NAME, release)
                _write_index_file(
                    final,
                    snap_release,
                    state=existing.status,
                    reason=reason,
                    import_lines=_import_lines_from_index(index_path),
                )
                retry_import = do_import and not (existing.import_done and existing.import_ok)
                if retry_import:
                    wheel_path = None
                    if import_wheel is not None:
                        wheel_path = _ensure_wheel(
                            import_wheel, final / WHEELS_DIRNAME, session=session
                        )
                    result = _run_import(
                        tree_root=final / TREE_DIRNAME,
                        wheel_path=wheel_path,
                        module=module,
                        runner=runner,
                    )
                    _apply_import(final, snap_release, existing, result)
                    code = EXIT_SUCCESS if result.ok else EXIT_IMPORT_FAILED
                    return InspectOutcome(code, index_path)
                if do_import:
                    return InspectOutcome(
                        EXIT_SUCCESS if existing.import_ok else EXIT_IMPORT_FAILED,
                        index_path,
                    )
                return InspectOutcome(EXIT_SUCCESS, index_path)

        if existing is not None and existing.status == "metadata-only" and not fetch:
            return InspectOutcome(EXIT_METADATA_ONLY, final / INDEX_NAME)

        staging = staging_dir(final)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)

        try:
            (staging / SNAPSHOT_NAME).write_text(dump_release_snapshot(release), encoding="utf-8")
            import_lines: list[str] | None = None
            import_result: ImportResult | None = None
            stored_read = read_wheel.filename if read_wheel and fetch else None
            stored_import = import_wheel.filename if import_wheel and fetch else None

            if fetch and read_wheel is not None:
                wheels_dir = staging / WHEELS_DIRNAME
                wheels_dir.mkdir()
                read_path = _ensure_wheel(read_wheel, wheels_dir, session=session)
                extract_wheel(read_path, staging / TREE_DIRNAME)
                if do_import:
                    import_path = read_path
                    if import_wheel is not None:
                        import_path = _ensure_wheel(import_wheel, wheels_dir, session=session)
                    import_result = _run_import(
                        tree_root=staging / TREE_DIRNAME,
                        wheel_path=import_path if import_wheel is not None else None,
                        module=module,
                        runner=runner,
                    )
                    import_lines = format_import_lines(import_result)
            elif do_import:
                import_result = ImportResult(
                    False,
                    module,
                    [],
                    "metadata-only; not importing",
                )
                import_lines = format_import_lines(import_result)

            index_state = state_name
            _write_index_file(
                staging,
                release,
                state=index_state,
                reason=reason,
                import_lines=import_lines,
            )
            write_state(
                staging,
                CacheState(
                    status="fetched" if fetch else "metadata-only",
                    reason=state_name,
                    max_bytes=limit,
                    read_wheel=stored_read,
                    import_wheel=stored_import,
                    import_done=bool(do_import),
                    import_ok=bool(import_result is not None and import_result.ok),
                ),
            )
            atomic_replace(staging, final)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        index_path = final / INDEX_NAME
        if not fetch:
            return InspectOutcome(EXIT_METADATA_ONLY, index_path)
        if do_import and import_result is not None and not import_result.ok:
            return InspectOutcome(EXIT_IMPORT_FAILED, index_path)
        return InspectOutcome(EXIT_SUCCESS, index_path)
