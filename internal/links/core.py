"""Declare, create, verify and remove the repository's directory junctions.

Each repository (the umbrella and, after step 07, each submodule) may commit a
``.links.yaml`` at its root::

    links:
      - path: .claude/skills/committing   # relative to that repository's root
        target: maintenance/plugin/skills/committing  # relative to the umbrella root
        why: one line

Junctions are never committed. ``sync`` registers each path in the owning
repository's ``info/exclude`` managed block *before* creating the junction,
``check`` verifies disk state against the declarations, ``clean`` removes the
junctions (never their targets). Spec and rules: docs/repo-wide/repo-layout.md.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

from links.fs import (
    create_junction,
    is_link_like,
    is_within,
    link_target,
    remove_link,
    same_path,
)

UMBRELLA_MARKER = ".umbrella-root"
MANIFEST_NAME = ".links.yaml"
BLOCK_BEGIN = "# BEGIN links (managed by `just links-sync`; do not edit)"
BLOCK_END = "# END links"
ENTRY_KEYS = {"path", "target", "why"}
# Directory names never walked when looking for undeclared junctions.
SCAN_PRUNE = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".astro",
    ".codegraph",
    ".pnpm-store",
}
# Umbrella-root-relative directories that are scratch space (gitignored).
SCAN_PRUNE_TOP = {"temp"}


class LinksError(Exception):
    pass


@dataclass(frozen=True)
class Link:
    repo: Path  # root of the repository that declares it
    path: str  # repo-relative POSIX path
    target: str  # umbrella-relative POSIX path
    why: str
    abs_path: Path
    abs_target: Path


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def info(self, message: str) -> None:
        self.infos.append(message)

    def print(self, *, quiet: bool = False) -> None:
        if not quiet:
            for line in self.infos:
                print(line)
        for line in self.warnings:
            print(f"warning: {line}")
        for line in self.errors:
            print(f"error: {line}")


# --- git helpers -----------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise LinksError(f"git {' '.join(args)} failed in {repo}: {result.stderr.strip()}")
    return result.stdout


def exclude_file(repo: Path) -> Path:
    # A submodule's .git is a file; ask git instead of assuming .git/info/exclude.
    out = _git(repo, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")
    return Path(out.strip())


def submodule_paths(repo: Path) -> list[str]:
    out = _git(repo, "ls-files", "--stage", "-z")
    paths = []
    for record in out.split("\0"):
        if record.startswith("160000 "):
            paths.append(record.split("\t", 1)[1])
    return paths


def tracked_under(repo: Path, rel: str) -> list[str]:
    return [p for p in _git(repo, "ls-files", "-z", "--", rel).split("\0") if p]


def ever_tracked(repo: Path, rel: str) -> bool:
    return bool(_git(repo, "log", "--all", "-1", "--format=%h", "--", rel).strip())


# --- discovery -------------------------------------------------------------


def find_umbrella_root(start: Path) -> Path:
    start = start.resolve()
    for directory in [start, *start.parents]:
        if (directory / UMBRELLA_MARKER).is_file():
            return directory
    raise LinksError(f"no {UMBRELLA_MARKER} found above {start}; pass --root")


def repositories(umbrella: Path) -> list[Path]:
    """The umbrella plus every checked-out submodule below it (recursive)."""
    found = [umbrella]
    queue = [umbrella]
    while queue:
        repo = queue.pop()
        for rel in submodule_paths(repo):
            sub = repo / rel
            if (sub / ".git").exists():
                found.append(sub)
                queue.append(sub)
    return found


def _check_rel(value: object, field_name: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LinksError(f"{where}: `{field_name}` must be a non-empty string")
    if "\\" in value:
        raise LinksError(f"{where}: `{field_name}` must use `/` separators: {value}")
    rel = PurePosixPath(value)
    if rel.is_absolute() or ":" in value or ".." in rel.parts or str(rel) == ".":
        raise LinksError(f"{where}: `{field_name}` must be a relative path inside: {value}")
    return rel.as_posix()


def load_manifest(repo: Path, umbrella: Path) -> list[Link]:
    manifest = repo / MANIFEST_NAME
    if not manifest.is_file():
        return []
    where = manifest.relative_to(umbrella).as_posix()
    try:
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise LinksError(f"{where}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict) or set(data) - {"links"}:
        raise LinksError(f"{where}: top level must be a mapping with only `links`")
    entries = data.get("links") or []
    if not isinstance(entries, list):
        raise LinksError(f"{where}: `links` must be a list")
    links = []
    for index, entry in enumerate(entries):
        item = f"{where} links[{index}]"
        if not isinstance(entry, dict):
            raise LinksError(f"{item}: must be a mapping")
        unknown = set(entry) - ENTRY_KEYS
        missing = ENTRY_KEYS - set(entry)
        if unknown or missing:
            raise LinksError(
                f"{item}: keys must be exactly {sorted(ENTRY_KEYS)}"
                f" (unknown {sorted(unknown)}, missing {sorted(missing)})"
            )
        path = _check_rel(entry["path"], "path", item)
        target = _check_rel(entry["target"], "target", item)
        why = entry["why"]
        if not isinstance(why, str) or not why.strip():
            raise LinksError(f"{item}: `why` must be a non-empty string")
        links.append(
            Link(
                repo=repo,
                path=path,
                target=target,
                why=why.strip(),
                abs_path=repo.joinpath(*PurePosixPath(path).parts),
                abs_target=umbrella.joinpath(*PurePosixPath(target).parts),
            )
        )
    return links


def load_all(umbrella: Path) -> tuple[list[Path], list[Link]]:
    repos = repositories(umbrella)
    links: list[Link] = []
    for repo in repos:
        links.extend(load_manifest(repo, umbrella))
    validate_static(links, repos)
    return repos, links


def _label(link: Link, umbrella: Path) -> str:
    return link.abs_path.relative_to(umbrella).as_posix()


def validate_static(links: list[Link], repos: list[Path]) -> None:
    """Rules that hold regardless of disk state. Any violation aborts."""
    problems = []
    umbrella = repos[0]
    for link in links:
        label = _label(link, umbrella)
        if is_within(link.abs_path, link.abs_target):
            problems.append(f"{label}: target `{link.target}` is the link itself or its ancestor")
        if is_within(link.abs_target, link.abs_path):
            problems.append(f"{label}: target `{link.target}` lies inside the link")
        # The path must belong to the declaring repository, not a nested one.
        for other in repos:
            if other != link.repo and is_within(other, link.repo):
                if is_within(link.abs_path, other) or is_within(other, link.abs_path):
                    problems.append(
                        f"{label}: path crosses into another repository"
                        f" ({other.relative_to(umbrella).as_posix()})"
                    )
    for i, a in enumerate(links):
        for b in links[i + 1 :]:
            if is_within(a.abs_path, b.abs_path) or is_within(b.abs_path, a.abs_path):
                problems.append(
                    f"{_label(a, umbrella)} and {_label(b, umbrella)}: declarations overlap"
                )
        for b in links:
            if a is not b and is_within(a.abs_target, b.abs_path):
                problems.append(
                    f"{_label(a, umbrella)}: target `{a.target}` points inside the link"
                    f" {_label(b, umbrella)} (no junction chains)"
                )
    if problems:
        raise LinksError("invalid link declarations:\n  " + "\n  ".join(problems))


# --- exclude managed block -------------------------------------------------


def exclude_pattern(link: Link) -> str:
    return f"/{link.path}/"


def read_block(path: Path) -> list[str]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if BLOCK_BEGIN not in lines:
        return []
    start = lines.index(BLOCK_BEGIN) + 1
    end = lines.index(BLOCK_END, start) if BLOCK_END in lines[start:] else len(lines)
    return [line for line in lines[start:end] if line.strip()]


def write_block(path: Path, patterns: list[str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    if BLOCK_BEGIN in lines:
        start = lines.index(BLOCK_BEGIN)
        end = lines.index(BLOCK_END, start) + 1 if BLOCK_END in lines[start:] else len(lines)
        del lines[start:end]
        while lines and not lines[-1].strip():
            lines.pop()
    if patterns:
        if lines:
            lines.append("")
        lines.extend([BLOCK_BEGIN, *sorted(set(patterns)), BLOCK_END])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", newline="\n")


def _block_paths(repo: Path) -> list[Path]:
    paths = []
    for pattern in read_block(exclude_file(repo)):
        rel = pattern.strip("/")
        if rel:
            paths.append(repo.joinpath(*PurePosixPath(rel).parts))
    return paths


# --- runtime checks --------------------------------------------------------


def _link_parent_problem(link: Link) -> str | None:
    current = link.repo
    for part in PurePosixPath(link.path).parts[:-1]:
        current = current / part
        if is_link_like(current):
            return f"parent `{current}` is a junction (links must not be created inside one)"
    return None


def _target_problem(link: Link, umbrella: Path) -> str | None:
    current = umbrella
    for part in PurePosixPath(link.target).parts:
        current = current / part
        if is_link_like(current):
            return f"target passes through the junction `{current.relative_to(umbrella)}`"
    return None


def inspect(link: Link, umbrella: Path, report: Report) -> str:
    """Classify one declaration. Returns ok / missing / wrong / real / skip / bad."""
    label = _label(link, umbrella)
    problem = _link_parent_problem(link) or _target_problem(link, umbrella)
    if problem:
        report.error(f"{label}: {problem}")
        return "bad"
    tracked = tracked_under(link.repo, link.path)
    if tracked:
        report.error(
            f"{label}: {len(tracked)} tracked file(s) under the link path"
            " (a checkout wrote through the junction? see repo-layout.md)"
        )
        return "bad"
    if ever_tracked(link.repo, link.path):
        report.warn(
            f"{label}: this path was tracked in history; run `just links-clean` before"
            " checking out such a commit and `just links-sync` afterwards"
        )
    if not link.abs_target.is_dir():
        report.warn(f"{label}: target `{link.target}` does not exist here; skipped")
        return "skip"
    if is_link_like(link.abs_path):
        current = link_target(link.abs_path)
        if current is not None and same_path(current, link.abs_target):
            return "ok"
        return "wrong"
    if link.abs_path.exists():
        report.error(f"{label}: a real file or directory already exists at the link path")
        return "real"
    return "missing"


def find_junctions(umbrella: Path) -> list[Path]:
    """Every link-like directory under the umbrella (not walking into any)."""
    found = []
    stack = [umbrella]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            if entry.name in SCAN_PRUNE:
                continue
            if directory == umbrella and entry.name in SCAN_PRUNE_TOP:
                continue
            path = Path(entry.path)
            if is_link_like(path):
                found.append(path)
            elif entry.is_dir(follow_symlinks=False):
                stack.append(path)
    return sorted(found)


# --- commands --------------------------------------------------------------


def sync(umbrella: Path, *, dry_run: bool = False) -> Report:
    report = Report()
    repos, links = load_all(umbrella)
    states = {link: inspect(link, umbrella, report) for link in links}
    declared = {os.path.normcase(str(link.abs_path)) for link in links}
    for repo in repos:
        exclude = exclude_file(repo)
        # Remove junctions that are no longer declared but still in the block.
        for stale in _block_paths(repo):
            if os.path.normcase(str(stale)) in declared:
                continue
            if is_link_like(stale):
                report.info(f"remove   {stale.relative_to(umbrella).as_posix()} (undeclared)")
                if not dry_run:
                    remove_link(stale)
        repo_links = [link for link in links if link.repo == repo]
        # Only paths that are or will be junctions; never hide real content.
        patterns = [
            exclude_pattern(link)
            for link in repo_links
            if states[link] in {"ok", "missing", "wrong"}
        ]
        if not dry_run:
            write_block(exclude, patterns)  # exclude first, then create (01-A)
        for link in repo_links:
            label = _label(link, umbrella)
            state = states[link]
            if state == "ok":
                report.info(f"ok       {label} -> {link.target}")
                continue
            if state not in {"missing", "wrong"}:
                continue
            if exclude_pattern(link) not in read_block(exclude) and not dry_run:
                report.error(f"{label}: could not register in {exclude}; not created")
                continue
            verb = "relink  " if state == "wrong" else "create  "
            report.info(f"{verb} {label} -> {link.target}")
            if dry_run:
                continue
            try:
                if state == "wrong":
                    remove_link(link.abs_path)
                create_junction(link.abs_path, link.abs_target)
            except OSError as exc:
                report.error(f"{label}: {exc}")
    return report


def check(umbrella: Path) -> Report:
    report = Report()
    repos, links = load_all(umbrella)
    declared = {os.path.normcase(str(link.abs_path)) for link in links}
    for link in links:
        label = _label(link, umbrella)
        state = inspect(link, umbrella, report)
        if state == "ok":
            report.info(f"ok       {label} -> {link.target}")
        elif state == "missing":
            report.error(f"{label}: junction is missing; run `just links-sync`")
        elif state == "wrong":
            report.error(
                f"{label}: junction points to {link_target(link.abs_path)}, not {link.target}"
                " (umbrella moved or copied?); run `just links-sync`"
            )
        if state in {"ok", "wrong"}:
            if exclude_pattern(link) not in read_block(exclude_file(link.repo)):
                report.error(
                    f"{label}: not registered in info/exclude; git would stage the"
                    " target's files and `git clean` may delete them. run `just links-sync`"
                )
    for junction in find_junctions(umbrella):
        if os.path.normcase(str(junction)) in declared:
            continue
        label = junction.relative_to(umbrella).as_posix()
        target = link_target(junction)
        detail = f" -> {target}" if target else ""
        if target is not None and not is_within(target, umbrella):
            report.error(f"{label}{detail}: undeclared junction pointing outside the umbrella")
        else:
            report.error(f"{label}{detail}: undeclared junction (add it to {MANIFEST_NAME})")
    for repo in repos:
        for stale in _block_paths(repo):
            if os.path.normcase(str(stale)) not in declared:
                report.warn(
                    f"{stale.relative_to(umbrella).as_posix()}: in info/exclude but not"
                    " declared; `just links-sync` removes it"
                )
    return report


def post_checkout(umbrella: Path) -> Report:
    """Cheap warning after a checkout: tracked files now sit under a link path."""
    report = Report()
    try:
        repos, links = load_all(umbrella)
    except LinksError as exc:
        report.warn(str(exc))
        return report
    for link in links:
        if tracked_under(link.repo, link.path):
            report.warn(
                f"{_label(link, umbrella)}: this commit tracks files at a junction path;"
                f" git may have written them into `{link.target}`. Check `git status` there,"
                " and use `just links-clean` before such checkouts (repo-layout.md)"
            )
    return report


def clean(umbrella: Path, *, dry_run: bool = False) -> Report:
    report = Report()
    repos = repositories(umbrella)
    links: list[Link] = []
    for repo in repos:
        try:
            links.extend(load_manifest(repo, umbrella))
        except LinksError as exc:  # still remove what the exclude block lists
            report.warn(str(exc))
    for repo in repos:
        candidates = {os.path.normcase(str(p)): p for p in _block_paths(repo)}
        for link in links:
            if link.repo == repo:
                candidates.setdefault(os.path.normcase(str(link.abs_path)), link.abs_path)
        for path in sorted(candidates.values()):
            label = path.relative_to(umbrella).as_posix()
            if is_link_like(path):
                report.info(f"remove   {label}")
                if not dry_run:
                    remove_link(path)
            elif path.exists():
                report.warn(f"{label}: not a junction; left untouched")
        if not dry_run:
            write_block(exclude_file(repo), [])
    return report
