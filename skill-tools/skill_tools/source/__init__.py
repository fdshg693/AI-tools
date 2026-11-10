"""Local and GitHub sources with immutable source identity information."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Protocol

from ..install.policy import DEFAULT_EXCLUDED_DIRECTORIES, BundlePolicy
from ..models import SourceError
from ..fs_links import is_link_like

_USER_AGENT = "skill-tools/0.1"
# Nested submodules are followed this deep (umbrella -> submodule -> ...).
_MAX_SUBMODULE_DEPTH = 3
_GITHUB_PREFIXES = (
    "https://github.com/",
    "http://github.com/",
    "ssh://git@github.com/",
    "git@github.com:",
)


def _github_repo_from_url(url: str, parent: tuple[str, str]) -> tuple[str, str]:
    """Return (owner, repository) for a ``.gitmodules`` URL hosted on github.com.

    Accepts https/ssh/scp-style GitHub URLs and URLs relative to the parent
    repository (``../other.git``). Anything else is refused: the catalog would
    otherwise silently miss the submodule's files.
    """
    value = url.strip()
    if value.startswith(("./", "../")):
        segments = [parent[0], parent[1]]
        for part in value.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if not segments:
                    raise SourceError(f"submodule URL escapes github.com: {url}")
                segments.pop()
            else:
                segments.append(part)
        parts = segments
    else:
        rest = next(
            (value[len(prefix) :] for prefix in _GITHUB_PREFIXES if value.startswith(prefix)),
            None,
        )
        if rest is None:
            raise SourceError(f"submodule URL is not on github.com: {url}")
        parts = [part for part in rest.split("/") if part]
    if len(parts) != 2:
        raise SourceError(f"submodule URL is not a GitHub repository: {url}")
    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[: -len(".git")]
    if not owner or not repository:
        raise SourceError(f"submodule URL is not a GitHub repository: {url}")
    return owner, repository


def _parse_gitmodules(text: str) -> dict[str, str]:
    """Map submodule path -> url from a ``.gitmodules`` file."""
    sections: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            sections.append({})
            continue
        key, sep, value = line.partition("=")
        if sep and sections:
            sections[-1][key.strip()] = value.strip()
    return {
        PurePosixPath(section["path"]).as_posix(): section["url"]
        for section in sections
        if section.get("path") and section.get("url")
    }


class CatalogSource(Protocol):
    """The source surface required by catalog discovery."""

    @property
    def descriptor(self) -> Mapping[str, str]: ...

    @property
    def fingerprint(self) -> Mapping[str, str]: ...

    def list_files(self, roots: Iterable[PurePosixPath]) -> tuple[PurePosixPath, ...]: ...

    def read_file(self, path: PurePosixPath) -> bytes: ...


def fingerprint_key(fingerprint: Mapping[str, str]) -> str:
    """Return a stable key for an index's source fingerprint."""

    encoded = json.dumps(
        dict(fingerprint), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def display_skill_path(relative_path: str, descriptor: Mapping[str, str] | None) -> str:
    """Return a locatable path: absolute for local sources, a GitHub blob URL otherwise."""

    relative = PurePosixPath(relative_path)
    if (
        not relative_path
        or relative.is_absolute()
        or ".." in relative.parts
        or "." in relative.parts
    ):
        return relative_path
    if not descriptor:
        return relative.as_posix()
    source_type = descriptor.get("type")
    if source_type == "local":
        raw_root = descriptor.get("path")
        if not isinstance(raw_root, str) or not raw_root:
            return relative.as_posix()
        return str((Path(raw_root).expanduser().resolve() / Path(*relative.parts)).resolve())
    if source_type == "github":
        owner = descriptor.get("owner")
        repository = descriptor.get("repository")
        ref = descriptor.get("commit") or descriptor.get("ref")
        if (
            not isinstance(owner, str)
            or not owner
            or not isinstance(repository, str)
            or not repository
            or not isinstance(ref, str)
            or not ref
        ):
            return relative.as_posix()
        owner_q = urllib.parse.quote(owner, safe="")
        repository_q = urllib.parse.quote(repository, safe="")
        ref_q = urllib.parse.quote(ref, safe="")
        path_q = urllib.parse.quote(relative.as_posix(), safe="/")
        return f"https://github.com/{owner_q}/{repository_q}/blob/{ref_q}/{path_q}"
    return relative.as_posix()


def _safe_remote_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise SourceError(f"GitHub returned an unsafe repository path: {value!r}")
    return path


class LocalSource:
    """Read a clone while excluding ignored files and rejecting symlink escape."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        if not self.root.is_dir():
            raise SourceError(f"local repository does not exist: {root}")
        self._visible_file_cache: tuple[PurePosixPath, ...] | None = None
        self._tree_digest: str | None = None

    @property
    def descriptor(self) -> Mapping[str, str]:
        return {"type": "local", "path": str(self.root)}

    @property
    def fingerprint(self) -> Mapping[str, str]:
        if self._tree_digest is None:
            digest = hashlib.sha256()
            for path in self._visible_files():
                digest.update(path.as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(self.read_file(path))
                digest.update(b"\0")
            self._tree_digest = digest.hexdigest()
        return {
            "type": "local",
            "path": str(self.root),
            "treeDigest": self._tree_digest,
        }

    def _resolve(self, path: PurePosixPath) -> Path:
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise SourceError(f"source path is unsafe: {path}")
        candidate = (self.root / Path(*path.parts)).resolve()
        if not candidate.is_relative_to(self.root):
            raise SourceError(f"source path escapes local repository: {path}")
        return candidate

    @staticmethod
    def _git_ls_files(directory: Path) -> list[bytes] | None:
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(directory),
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "-z",
                ],
                capture_output=True,
                check=False,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        return [raw for raw in result.stdout.split(b"\0") if raw]

    def _git_listing(self) -> list[bytes] | None:
        """``git ls-files`` of the repository plus its checked-out submodules.

        A submodule appears in its parent's listing as one gitlink path; its
        files are listed in the submodule and prefixed with that path.
        """

        top = self._git_ls_files(self.root)
        if top is None:
            return None
        listing: list[bytes] = []
        pending = [(b"", top, 0)]
        while pending:
            prefix, entries, depth = pending.pop()
            for raw in entries:
                full = prefix + raw
                directory = self.root / Path(os.fsdecode(full))
                if (
                    depth < _MAX_SUBMODULE_DEPTH
                    and (directory / ".git").exists()
                    and (directory.is_dir() and not is_link_like(directory))
                ):
                    nested = self._git_ls_files(directory)
                    if nested is not None:
                        pending.append((full + b"/", nested, depth + 1))
                        continue
                listing.append(full)
        return listing

    def _git_visible_files(self) -> tuple[PurePosixPath, ...] | None:
        listing = self._git_listing()
        if listing is None:
            return None

        paths: set[PurePosixPath] = set()
        for raw_path in listing:
            relative = Path(os.fsdecode(raw_path))
            if relative.is_absolute() or ".." in relative.parts:
                raise SourceError(f"git returned an unsafe source path: {relative}")
            path = PurePosixPath(relative.as_posix())
            candidate = self._resolve(path)
            # A file reached through a junction or symlink that git still lists
            # (not excluded) resolves elsewhere; skip it so nothing is counted twice.
            lexical = self.root / Path(*path.parts)
            if os.path.normcase(str(candidate)) != os.path.normcase(str(lexical)):
                continue
            if candidate.is_file():
                paths.add(path)
        return tuple(sorted(paths))

    def _visible_files(self) -> tuple[PurePosixPath, ...]:
        if self._visible_file_cache is not None:
            return self._visible_file_cache

        paths = self._git_visible_files()
        if paths is None:
            # Without git, prune dependency and cache trees that would otherwise
            # dwarf the repository and make every command appear to hang.
            discovered: set[PurePosixPath] = set()
            for directory, child_dirs, child_files in os.walk(self.root, followlinks=False):
                directory_path = Path(directory)
                child_dirs[:] = [
                    child
                    for child in child_dirs
                    if child not in DEFAULT_EXCLUDED_DIRECTORIES
                    and not is_link_like(directory_path / child)
                ]
                for child in child_files:
                    candidate = directory_path / child
                    # Symlinked files are skipped instead of resolved: `_resolve` costs a
                    # realpath syscall per file, which dominates the walk on large trees.
                    if is_link_like(candidate):
                        continue
                    relative = PurePosixPath(candidate.relative_to(self.root).as_posix())
                    discovered.add(relative)
            paths = tuple(sorted(discovered))

        self._visible_file_cache = paths
        return paths

    def list_files(self, roots: Iterable[PurePosixPath]) -> tuple[PurePosixPath, ...]:
        roots = tuple(roots)
        for root in roots:
            self._resolve(root)
        return tuple(
            path
            for path in self._visible_files()
            if any(path.is_relative_to(root) for root in roots)
        )

    def include_candidates(
        self, root: PurePosixPath, policy: BundlePolicy
    ) -> tuple[PurePosixPath, ...]:
        """Return include-listed files under ``root`` that the listing cannot see.

        Git hides ignored/untracked files (``.env`` and friends) from
        ``list_files``, so an explicit ``.skill-tools`` include has to look at the
        disk directly. The walk mirrors ``_visible_files``: default-excluded
        dependency/cache directories are pruned and symlinks are skipped, so an
        include can never reach into ``.venv``-style trees. Paths are returned
        relative to ``root``; the caller deduplicates against ``list_files``.
        """

        directory_root = self._resolve(root)
        candidates: set[PurePosixPath] = set()
        for directory, child_dirs, child_files in os.walk(directory_root, followlinks=False):
            directory_path = Path(directory)
            child_dirs[:] = [
                child
                for child in child_dirs
                if child not in DEFAULT_EXCLUDED_DIRECTORIES
                and not is_link_like(directory_path / child)
            ]
            for child in child_files:
                candidate = directory_path / child
                if is_link_like(candidate):
                    continue
                relative = PurePosixPath(candidate.relative_to(directory_root).as_posix())
                if policy.included(relative):
                    candidates.add(relative)
        return tuple(sorted(candidates))

    def read_file(self, path: PurePosixPath) -> bytes:
        candidate = self._resolve(path)
        if not candidate.is_file():
            raise SourceError(f"source file does not exist: {path}")
        return candidate.read_bytes()


class GitHubSource:
    """Fetch a GitHub ref as one resolved commit tree.

    Submodules (gitlinks) are followed: their files appear under the submodule
    path and are read from the submodule's GitHub repository at the recorded
    commit. Set ``GITHUB_TOKEN`` to raise the API rate limit.
    """

    def __init__(self, owner: str, repository: str, ref: str = "main") -> None:
        if not owner or "/" in owner or not repository or "/" in repository or not ref:
            raise SourceError(
                "GitHub owner, repository, and ref must be non-empty single path segments"
            )
        self.owner = owner
        self.repository = repository
        self.ref = ref
        self.commit_sha = self._resolve_commit()
        # path -> (repository API base, blob sha)
        self._tree: dict[PurePosixPath, tuple[str, str]] = {}
        self._load_tree(self._repo_api, (owner, repository), self.commit_sha, PurePosixPath(), 0)
        self._blob_cache: dict[PurePosixPath, bytes] = {}

    @property
    def descriptor(self) -> Mapping[str, str]:
        return {
            "type": "github",
            "owner": self.owner,
            "repository": self.repository,
            "ref": self.ref,
            "commit": self.commit_sha,
        }

    @property
    def fingerprint(self) -> Mapping[str, str]:
        return {
            "type": "github",
            "owner": self.owner,
            "repository": self.repository,
            "commit": self.commit_sha,
        }

    @property
    def _repo_api(self) -> str:
        return self._api_for(self.owner, self.repository)

    @staticmethod
    def _api_for(owner: str, repository: str) -> str:
        owner_q = urllib.parse.quote(owner, safe="")
        repository_q = urllib.parse.quote(repository, safe="")
        return f"https://api.github.com/repos/{owner_q}/{repository_q}"

    def _request_json(self, url: str) -> object:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body)
                message = parsed.get("message", body) if isinstance(parsed, dict) else body
            except json.JSONDecodeError:
                message = body
            rate_remaining = exc.headers.get("X-RateLimit-Remaining")
            suffix = " (GitHub rate limit exhausted)" if rate_remaining == "0" else ""
            raise SourceError(f"GitHub API returned HTTP {exc.code}: {message}{suffix}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SourceError(f"could not read GitHub API: {exc}") from exc

    def _resolve_commit(self) -> str:
        ref = urllib.parse.quote(self.ref, safe="")
        data = self._request_json(f"{self._repo_api}/commits/{ref}")
        sha = data.get("sha") if isinstance(data, dict) else None
        if not isinstance(sha, str) or not sha:
            raise SourceError("GitHub commit response did not contain a SHA")
        return sha

    def _load_tree(
        self,
        repo_api: str,
        repo: tuple[str, str],
        commit_sha: str,
        prefix: PurePosixPath,
        depth: int,
    ) -> None:
        data = self._request_json(f"{repo_api}/git/trees/{commit_sha}?recursive=1")
        if not isinstance(data, dict) or data.get("truncated") is True:
            raise SourceError(
                "GitHub recursive tree is unavailable or truncated; refusing incomplete catalog"
            )
        tree = data.get("tree")
        if not isinstance(tree, list):
            raise SourceError("GitHub tree response did not contain a tree list")
        blobs: dict[PurePosixPath, str] = {}
        gitlinks: dict[str, str] = {}
        for entry in tree:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("type")
            raw_path, sha = entry.get("path"), entry.get("sha")
            if kind == "commit":
                if not isinstance(raw_path, str) or not isinstance(sha, str):
                    raise SourceError("GitHub tree contained an invalid submodule entry")
                gitlinks[_safe_remote_path(raw_path).as_posix()] = sha
                continue
            if kind != "blob":
                continue
            if not isinstance(raw_path, str) or not isinstance(sha, str):
                raise SourceError("GitHub tree contained an invalid blob entry")
            if entry.get("mode") == "120000":
                raise SourceError(f"GitHub tree contains an unsupported symlink: {raw_path}")
            path = _safe_remote_path(raw_path)
            if path in blobs:
                raise SourceError(f"GitHub tree contains duplicate file path: {path}")
            blobs[path] = sha
        for path, sha in blobs.items():
            full = prefix / path
            if full in self._tree:
                raise SourceError(f"GitHub tree contains duplicate file path: {full}")
            self._tree[full] = (repo_api, sha)
        if not gitlinks:
            return
        if depth >= _MAX_SUBMODULE_DEPTH:
            raise SourceError(f"submodules nested deeper than {_MAX_SUBMODULE_DEPTH} levels")
        gitmodules_sha = blobs.get(PurePosixPath(".gitmodules"))
        if gitmodules_sha is None:
            raise SourceError("GitHub tree has submodules but no .gitmodules")
        gitmodules = self._read_blob(repo_api, gitmodules_sha, prefix / ".gitmodules")
        urls = _parse_gitmodules(gitmodules.decode("utf-8"))
        for path, sha in sorted(gitlinks.items()):
            url = urls.get(path)
            if url is None:
                raise SourceError(f"submodule {prefix / path} is missing from .gitmodules")
            sub_repo = _github_repo_from_url(url, repo)
            self._load_tree(self._api_for(*sub_repo), sub_repo, sha, prefix / path, depth + 1)

    def list_files(self, roots: Iterable[PurePosixPath]) -> tuple[PurePosixPath, ...]:
        roots = tuple(roots)
        for root in roots:
            if root.is_absolute() or ".." in root.parts or "." in root.parts:
                raise SourceError(f"source root is unsafe: {root}")
        return tuple(
            path for path in sorted(self._tree) if any(path.is_relative_to(root) for root in roots)
        )

    def read_file(self, path: PurePosixPath) -> bytes:
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise SourceError(f"source path is unsafe: {path}")
        if path in self._blob_cache:
            return self._blob_cache[path]
        entry = self._tree.get(path)
        if entry is None:
            raise SourceError(f"GitHub source file does not exist: {path}")
        repo_api, sha = entry
        decoded = self._read_blob(repo_api, sha, path)
        self._blob_cache[path] = decoded
        return decoded

    def _read_blob(self, repo_api: str, sha: str, path: PurePosixPath) -> bytes:
        data = self._request_json(f"{repo_api}/git/blobs/{sha}")
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            raise SourceError(f"GitHub blob response for {path} was not base64 content")
        content = data.get("content")
        if not isinstance(content, str):
            raise SourceError(f"GitHub blob response for {path} did not contain content")
        try:
            return base64.b64decode(content.replace("\n", ""), validate=True)
        except ValueError as exc:
            raise SourceError(f"GitHub blob response for {path} was invalid base64") from exc
