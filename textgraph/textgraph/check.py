from __future__ import annotations

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .resolve import (
    EXACT,
    GIT_RENAME,
    UNIQUE_SUFFIX,
    UNRESOLVED,
    _join,
    _parent,
    _split_target,
    fallback_candidates,
    resolve_link,
)
from .scan import is_script_file, list_git_files, read_source_text, stored_links_from_text
from .store import StoredEdge, GraphStore

APPLYABLE = frozenset({UNIQUE_SUFFIX, GIT_RENAME})
AMBIGUOUS = "ambiguous"
SUGGESTED = "suggested"


@dataclass(frozen=True)
class Finding:
    source: str
    raw: str
    kind: str
    line: int
    status: str
    confidence: str
    suggested: tuple[str, ...]
    replacement: str | None

    @property
    def applyable(self) -> bool:
        return (
            self.status == SUGGESTED
            and self.confidence in APPLYABLE
            and self.replacement is not None
        )


def find_broken_links(root: Path, store: GraphStore, *, scripts: bool = False) -> list[Finding]:
    git_files = {path.replace("\\", "/") for path in list_git_files(root)}
    findings: list[Finding] = []
    for edge in store.all_links():
        finding = _finding_for_edge(root, edge, git_files)
        if finding is not None:
            findings.append(finding)
    if scripts:
        for edge in _script_edges(root, git_files):
            finding = _finding_for_edge(root, edge, git_files)
            if finding is not None:
                findings.append(finding)
    findings.sort(key=lambda item: (item.source, item.line, item.raw))
    return findings


def _script_edges(root: Path, git_files: set[str]) -> list[StoredEdge]:
    edges: list[StoredEdge] = []
    for path in sorted(p for p in git_files if is_script_file(p)):
        text = read_source_text(root, path)
        for link in stored_links_from_text(text, path, git_files):
            edges.append(
                StoredEdge(
                    source=path,
                    raw=link.raw,
                    kind=link.kind,
                    line=link.line,
                    resolved=link.resolved,
                    confidence=link.confidence,
                )
            )
    return edges


def _finding_for_edge(root: Path, edge: StoredEdge, git_files: set[str]) -> Finding | None:
    if not _is_broken(edge, git_files):
        return None
    return _suggest(root, edge, git_files)


def git_rename_destinations(
    root: Path,
    *,
    basename: str,
    old_path: str | None,
    current_files: set[str],
) -> list[str]:
    if not (root / ".git").exists() or not basename:
        return []
    pathspecs = []
    if old_path:
        pathspecs.append(old_path)
    pathspecs.extend([basename, f"**/{basename}"])
    result = subprocess.run(
        [
            "git",
            "log",
            "--diff-filter=R",
            "--name-status",
            "--pretty=format:",
            "--",
            *pathspecs,
        ],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    pairs: list[tuple[str, str]] = []
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        parsed = _parse_rename_line(line)
        if parsed is None:
            continue
        src, dest = parsed
        if dest not in current_files:
            continue
        pairs.append((src, dest))
    if old_path:
        exact = _unique_keep_order(dest for src, dest in pairs if src == old_path)
        if exact:
            return exact
    return _unique_keep_order(
        dest
        for src, dest in pairs
        if PurePosixPath(src).name == basename or PurePosixPath(dest).name == basename
    )


def preview_hunks(root: Path, findings: list[Finding]) -> list[str]:
    hunks: list[str] = []
    for finding in findings:
        line = _read_line(root, finding.source, finding.line)
        if line is None or finding.replacement is None:
            continue
        patched = replace_raw_in_line(line, finding.raw, finding.replacement, finding.kind)
        if patched is None:
            continue
        hunks.append(
            "\n".join(
                (
                    f"--- {finding.source}:{finding.line}",
                    f"- {_display_line(line)}",
                    f"+ {_display_line(patched)}",
                )
            )
        )
    return hunks


def apply_findings(root: Path, findings: list[Finding]) -> list[Finding]:
    failed: list[Finding] = []
    by_source: dict[str, list[Finding]] = {}
    for finding in findings:
        by_source.setdefault(finding.source, []).append(finding)
    for source in sorted(by_source):
        path = _abs(root, source)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OSError(f"failed to read {source}: {exc}") from exc
        lines = text.splitlines(keepends=True)
        changed = False
        for finding in by_source[source]:
            idx = finding.line - 1
            if idx < 0 or idx >= len(lines) or finding.replacement is None:
                failed.append(finding)
                continue
            patched = replace_raw_in_line(
                lines[idx], finding.raw, finding.replacement, finding.kind
            )
            if patched is None:
                failed.append(finding)
                continue
            lines[idx] = patched
            changed = True
        if changed:
            try:
                path.write_text("".join(lines), encoding="utf-8")
            except OSError as exc:
                raise OSError(f"failed to write {source}: {exc}") from exc
    return failed


def replace_raw_in_line(line: str, raw: str, new: str, kind: str) -> str | None:
    body, ending = _split_keepends(line)
    replaced = _replace_body(body, raw, new, kind)
    if replaced is None:
        return None
    return replaced + ending


def rewrite_raw(original_raw: str, target: str, source: str) -> str:
    path_part, anchor = _split_target(original_raw)
    if path_part.startswith("./") or path_part.startswith("../"):
        new_path = _posix_relpath(target, _parent(source))
    else:
        new_path = target
    if anchor:
        return f"{new_path}#{anchor}"
    return new_path


def _is_broken(edge: StoredEdge, git_files: set[str]) -> bool:
    if edge.confidence == UNRESOLVED or not edge.resolved:
        return True
    return edge.resolved not in git_files


def _suggest(root: Path, edge: StoredEdge, git_files: set[str]) -> Finding | None:
    hit = resolve_link(edge.raw, edge.source, git_files)
    if hit.resolved is not None and hit.confidence == EXACT:
        return None
    if hit.resolved is not None and hit.confidence != UNRESOLVED:
        return _finding(
            edge,
            status=SUGGESTED,
            confidence=hit.confidence,
            suggested=(hit.resolved,),
        )
    path_part, _anchor = _split_target(edge.raw)
    basename = PurePosixPath(path_part).name if path_part else ""
    ambiguous = fallback_candidates(edge.raw, git_files)
    # Old resolved paths can still git-rename uniquely when the basename is
    # now shared. Live script scans have no stored target, so the raw path
    # (joined to the source directory) is the next-best old path.
    old_path = edge.resolved
    if not old_path and path_part:
        old_path = _join(_parent(edge.source), path_part)
    if old_path:
        renamed = git_rename_destinations(
            root,
            basename=basename,
            old_path=old_path,
            current_files=git_files,
        )
    elif not ambiguous:
        renamed = git_rename_destinations(
            root,
            basename=basename,
            old_path=None,
            current_files=git_files,
        )
    else:
        renamed = []
    if len(renamed) == 1:
        return _finding(
            edge,
            status=SUGGESTED,
            confidence=GIT_RENAME,
            suggested=(renamed[0],),
        )
    if len(renamed) > 1:
        return _finding(
            edge,
            status=AMBIGUOUS,
            confidence=AMBIGUOUS,
            suggested=tuple(renamed),
        )
    if len(ambiguous) > 1:
        return _finding(
            edge,
            status=AMBIGUOUS,
            confidence=AMBIGUOUS,
            suggested=tuple(ambiguous),
        )
    return _finding(
        edge,
        status=UNRESOLVED,
        confidence=UNRESOLVED,
        suggested=(),
    )


def _finding(
    edge: StoredEdge,
    *,
    status: str,
    confidence: str,
    suggested: tuple[str, ...],
) -> Finding:
    replacement = None
    if len(suggested) == 1:
        replacement = rewrite_raw(edge.raw, suggested[0], edge.source)
    return Finding(
        source=edge.source,
        raw=edge.raw,
        kind=edge.kind,
        line=edge.line,
        status=status,
        confidence=confidence,
        suggested=suggested,
        replacement=replacement,
    )


def _parse_rename_line(line: str) -> tuple[str, str] | None:
    if not line or not line.startswith("R") or "\t" not in line:
        return None
    parts = line.split("\t")
    if len(parts) < 3:
        return None
    src = parts[1].replace("\\", "/")
    dest = parts[2].replace("\\", "/")
    if not src or not dest:
        return None
    return src, dest


def _unique_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _posix_relpath(target: str, start_dir: str) -> str:
    start_parts = [part for part in start_dir.split("/") if part not in ("", ".")]
    target_parts = [part for part in target.split("/") if part not in ("", ".")]
    common = 0
    for left, right in zip(start_parts, target_parts):
        if left != right:
            break
        common += 1
    ups = [".."] * (len(start_parts) - common)
    downs = target_parts[common:]
    parts = ups + downs
    if not parts:
        return "."
    rel = "/".join(parts)
    if not rel.startswith(".."):
        return f"./{rel}"
    return rel


def _replace_body(body: str, raw: str, new: str, kind: str) -> str | None:
    needles: list[tuple[str, str]] = []
    if kind in {"markdown", "image"}:
        needles.extend(
            (
                (f"]({raw}", f"]({new}"),
                (f"](<{raw}>", f"](<{new}>"),
            )
        )
    elif kind == "wiki":
        needles.append((f"[[{raw}", f"[[{new}"))
    elif kind == "at":
        needles.append((f"@{raw}", f"@{new}"))
    elif kind == "ref":
        needles.extend(
            (
                (f"]: {raw}", f"]: {new}"),
                (f"]:{raw}", f"]:{new}"),
                (f"]: <{raw}>", f"]: <{new}>"),
            )
        )
    needles.append((raw, new))
    for needle, repl in needles:
        index = body.find(needle)
        if index != -1:
            return body[:index] + repl + body[index + len(needle) :]
    return None


def _split_keepends(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1], line[-1]
    return line, ""


def _display_line(line: str) -> str:
    body, _ending = _split_keepends(line)
    return body


def _read_line(root: Path, source: str, line: int) -> str | None:
    path = _abs(root, source)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.splitlines(keepends=True)
    if line < 1 or line > len(lines):
        return None
    return lines[line - 1]


def _abs(root: Path, posix_path: str) -> Path:
    return root.joinpath(*posix_path.split("/"))
