"""Build ``index.md``: metadata, status, file tree, recommended paths, import."""

from __future__ import annotations

import zipfile
from collections.abc import Iterable
from pathlib import Path

from pyinspect_core.config import RECOMMENDED_PATH_LIMIT, TREE_ENTRY_LIMIT
from pyinspect_core.pypi import ProjectRelease


def extract_wheel(wheel_path: Path, dest: Path) -> None:
    """Open the wheel as a zip. Never run setup.py."""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel_path) as zf:
        zf.extractall(dest)


def _posix_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def iter_tree_entries(tree_root: Path, cache_root: Path) -> list[tuple[str, int]]:
    if not tree_root.is_dir():
        return []
    entries: list[tuple[str, int]] = []
    for path in sorted(tree_root.rglob("*")):
        if not path.is_file():
            continue
        entries.append((_posix_rel(path, cache_root), path.stat().st_size))
    return entries


def format_file_tree(entries: list[tuple[str, int]], *, limit: int = TREE_ENTRY_LIMIT) -> list[str]:
    if not entries:
        return ["- (none)"]
    shown = entries[:limit]
    lines = [f"- {name} ({size} bytes)" for name, size in shown]
    if len(entries) > limit:
        lines.append(f"- (truncated: showing {limit} of {len(entries)} entries)")
    return lines


def recommended_paths(tree_root: Path, cache_root: Path) -> list[str]:
    """Deterministic entry points, max 8, no interpretation text."""
    if not tree_root.is_dir():
        return []

    found: list[Path] = []

    readmes = sorted(
        p for p in tree_root.iterdir() if p.is_file() and p.name.upper().startswith("README")
    )
    found.extend(readmes)

    typed = sorted(p for p in tree_root.rglob("py.typed") if p.is_file() and p.stat().st_size > 0)
    found.extend(typed)

    top_packages = [
        p
        for p in tree_root.iterdir()
        if p.is_dir()
        and not p.name.endswith(".dist-info")
        and not p.name.endswith(".data")
        and (p / "__init__.py").is_file()
    ]
    regular = sorted(p for p in top_packages if not p.name.startswith("_"))
    private = sorted(p for p in top_packages if p.name.startswith("_"))
    packages = regular if regular else private
    inits = [p / "__init__.py" for p in packages]

    metas = sorted(tree_root.glob("*.dist-info/METADATA"))
    reserved = 1 if metas else 0
    remaining = RECOMMENDED_PATH_LIMIT - len(found) - reserved
    if remaining > 0:
        found.extend(inits[:remaining])
    found.extend(metas)

    unique: list[str] = []
    seen: set[str] = set()
    for path in found:
        rel = _posix_rel(path, cache_root)
        if rel in seen:
            continue
        seen.add(rel)
        unique.append(rel)
        if len(unique) >= RECOMMENDED_PATH_LIMIT:
            break
    return unique


def render_index(
    release: ProjectRelease,
    *,
    state: str,
    reason: str,
    tree_lines: Iterable[str],
    recommended: Iterable[str],
    import_lines: Iterable[str] | None = None,
) -> str:
    requires_dist = release.requires_dist or []
    if requires_dist:
        dist_block = "\n".join(f"  - {item}" for item in requires_dist)
        dist_field = "\n" + dist_block
    else:
        dist_field = " (none)"

    yanked_line = f"- Yanked: {str(release.yanked).lower()}"
    if release.yanked and release.yanked_reason:
        yanked_line += f" ({release.yanked_reason})"

    rec = list(recommended)
    rec_lines = [f"- {path}" for path in rec] if rec else ["- (none)"]

    lines = [
        f"# {release.name} {release.version}",
        "",
        "## Metadata",
        "",
        f"- Name: {release.name}",
        f"- Version: {release.version}",
        f"- Summary: {release.summary or '(none)'}",
        f"- Requires-Python: {release.requires_python or '(none)'}",
        f"- Requires-Dist:{dist_field}",
        f"- Home-page: {release.home_page or '(none)'}",
        yanked_line,
        "",
        "## Status",
        "",
        f"- State: {state}",
        f"- Reason: {reason}",
        "",
        "## File tree",
        "",
        *tree_lines,
        "",
        "## Recommended paths",
        "",
        *rec_lines,
        "",
    ]
    if import_lines is not None:
        lines.extend(["## Import", "", *import_lines, ""])
    return "\n".join(lines)


def upsert_import_section(markdown: str, import_lines: Iterable[str]) -> str:
    body = "\n".join(import_lines)
    marker = "\n## Import\n"
    block = f"## Import\n\n{body}\n"
    if marker in "\n" + markdown:
        prefix, _sep, rest = markdown.partition("## Import")
        # Drop the old Import section (through EOF — it is last).
        return prefix.rstrip() + "\n\n" + block
    return markdown.rstrip() + "\n\n" + block
