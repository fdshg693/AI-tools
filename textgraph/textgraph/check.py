from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .resolve import (
    EXACT,
    GIT_RENAME,
    GIT_RENAME_BASENAME,
    UNIQUE_BASENAME,
    UNIQUE_SUFFIX,
    UNRESOLVED,
    _join,
    _parent,
    _split_target,
    directories_of,
    fallback_candidates,
    narrow_candidates,
    resolve_link,
)
from .scan import is_script_file, list_git_files, read_source_text, stored_links_from_text
from .store import StoredEdge, GraphStore

APPLYABLE = frozenset({UNIQUE_SUFFIX, GIT_RENAME})
AMBIGUOUS = "ambiguous"
SUGGESTED = "suggested"
EXTERNAL = "external"
ON_DISK = "on-disk"


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
    git_dirs = directories_of(git_files)
    findings: list[Finding] = []
    for edge in store.all_links():
        finding = _finding_for_edge(root, edge, git_files, git_dirs)
        if finding is not None:
            findings.append(finding)
    if scripts:
        for edge in _script_edges(root, git_files):
            finding = _finding_for_edge(root, edge, git_files, git_dirs)
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


def _finding_for_edge(
    root: Path, edge: StoredEdge, git_files: set[str], git_dirs: frozenset[str]
) -> Finding | None:
    if not _is_broken(edge, git_files, git_dirs):
        return None
    # The written path is not in the index but exists on disk: a submodule
    # file, a file above the repository root, or a gitignored artifact. It is
    # not broken, so it gets no candidates and is never rewritten.
    if _exists_on_disk(root, edge.raw, edge.source):
        return _finding(edge, status=EXTERNAL, confidence=ON_DISK, suggested=())
    return _suggest(root, edge, git_files)


def _exists_on_disk(root: Path, raw: str, source: str) -> bool:
    """Whether the written path names a file or directory on disk.

    Mirrors the exact steps of the resolver (source-relative, then
    root-relative, each also with ``.md`` appended when there is no
    extension), but joins OS paths so ``..`` may leave the root.
    """
    path_part, _anchor = _split_target(raw)
    rel_parts = [part for part in path_part.split("/") if part]
    if not rel_parts:
        return False
    bases: list[Path] = []
    if not path_part.startswith("/"):
        source_dir = _parent(source)
        bases.append(_abs(root, source_dir) if source_dir else root)
    bases.append(root)
    variants = [rel_parts]
    if not PurePosixPath(path_part).suffix:
        variants.append([*rel_parts[:-1], f"{rel_parts[-1]}.md"])
    for base in bases:
        for parts in variants:
            try:
                if os.path.exists(os.path.normpath(os.path.join(base, *parts))):
                    return True
            except (OSError, ValueError):
                continue
    return False


@dataclass(frozen=True)
class RenameDestinations:
    """Committed rename destinations that still exist.

    ``exact`` holds renames whose old path equals the link's old path.
    ``basename`` holds renames that only share the basename; they are hints,
    not proof, so they are never applied automatically.
    """

    exact: tuple[str, ...] = ()
    basename: tuple[str, ...] = ()


def git_rename_destinations(
    root: Path,
    *,
    basename: str,
    old_path: str | None,
    current_files: set[str],
) -> RenameDestinations:
    if not (root / ".git").exists() or not basename:
        return RenameDestinations()
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
        return RenameDestinations()
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
            return RenameDestinations(exact=tuple(exact))
    return RenameDestinations(
        basename=tuple(
            _unique_keep_order(
                dest
                for src, dest in pairs
                if PurePosixPath(src).name == basename or PurePosixPath(dest).name == basename
            )
        )
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
            text = _read_raw_text(path)
        except OSError as exc:
            raise OSError(f"failed to read {source}: {exc}") from exc
        lines = _split_lines_keepends(text)
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
                path.write_text("".join(lines), encoding="utf-8", newline="")
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


def _is_broken(edge: StoredEdge, git_files: set[str], git_dirs: frozenset[str]) -> bool:
    """A link needs attention unless it resolved exactly to something that exists.

    Non-exact resolutions (``unique-suffix`` / ``unique-basename``) only work
    because the resolver guessed; the written path itself is wrong, so they
    are reported. Wiki links are the exception: ``[[name]]`` means "the page
    called name", so a unique basename is their intended resolution.
    """
    if edge.confidence == UNRESOLVED or not edge.resolved:
        return True
    if edge.resolved not in git_files and edge.resolved not in git_dirs:
        return True
    return not _is_intended_resolution(edge.kind, edge.confidence)


def _is_intended_resolution(kind: str, confidence: str) -> bool:
    return confidence == EXACT or (kind == "wiki" and confidence == UNIQUE_BASENAME)


def _suggest(root: Path, edge: StoredEdge, git_files: set[str]) -> Finding | None:
    hit = resolve_link(edge.raw, edge.source, git_files)
    if hit.resolved is not None and _is_intended_resolution(edge.kind, hit.confidence):
        return None
    # A basename hit that shares no directory name with the link is a
    # coincidence (another README.md, another SKILL.md), not a candidate.
    if (
        hit.resolved is not None
        and hit.confidence != UNRESOLVED
        and (hit.confidence != UNIQUE_BASENAME or narrow_candidates(edge.raw, [hit.resolved]))
    ):
        return _finding(
            edge,
            status=SUGGESTED,
            confidence=hit.confidence,
            suggested=(hit.resolved,),
        )
    path_part, _anchor = _split_target(edge.raw)
    basename = PurePosixPath(path_part).name if path_part else ""
    ambiguous = narrow_candidates(edge.raw, fallback_candidates(edge.raw, git_files))
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
        renamed = RenameDestinations()
    for destinations, confidence in (
        (renamed.exact, GIT_RENAME),
        (tuple(narrow_candidates(edge.raw, renamed.basename)), GIT_RENAME_BASENAME),
    ):
        if len(destinations) == 1:
            return _finding(
                edge,
                status=SUGGESTED,
                confidence=confidence,
                suggested=destinations,
            )
        if len(destinations) > 1:
            return _finding(
                edge,
                status=AMBIGUOUS,
                confidence=AMBIGUOUS,
                suggested=destinations,
            )
    if len(ambiguous) == 1:
        # Only basename hits can be narrowed down to one (suffix hits always
        # contain the link's directory names), and a basename guess is never
        # applied automatically.
        return _finding(
            edge,
            status=SUGGESTED,
            confidence=UNIQUE_BASENAME,
            suggested=tuple(ambiguous),
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
        text = _read_raw_text(path)
    except OSError:
        return None
    lines = _split_lines_keepends(text)
    if line < 1 or line > len(lines):
        return None
    return lines[line - 1]


def _read_raw_text(path: Path) -> str:
    # newline="" keeps CRLF / mixed endings intact (Path.read_text has no
    # newline argument before Python 3.13).
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _split_lines_keepends(text: str) -> list[str]:
    # Split on "\n" only, matching extract._line_at. str.splitlines would also
    # break on a lone "\r", "\v", U+2028 etc. and shift line numbers.
    lines = text.split("\n")
    out = [line + "\n" for line in lines[:-1]]
    if lines[-1]:
        out.append(lines[-1])
    return out


def _abs(root: Path, posix_path: str) -> Path:
    return root.joinpath(*posix_path.split("/"))
