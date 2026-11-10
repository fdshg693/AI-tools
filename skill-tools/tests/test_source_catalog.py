from __future__ import annotations

import base64
from pathlib import Path, PurePosixPath

import pytest

from skill_tools.catalog import discover_catalog, select_records
from skill_tools.models import CatalogError, SourceError
from skill_tools.source import GitHubSource, LocalSource, display_skill_path

CATALOG = """\
tools:
  claude-code:
    plugins:
      - path: plugins/one
        kind: plugin
        skills_layout: subdir
  cursor:
    plugins:
      - path: plugins/two
        kind: plugin
        skills_layout: direct
"""


def _skill(name: str) -> bytes:
    return f"---\nname: {name}\ndescription: Description for {name}\n---\n\n# {name}\n".encode()


def make_repository(root: Path) -> Path:
    root.mkdir()
    (root / "ai-tools.yaml").write_text(CATALOG, encoding="utf-8")
    alpha = root / "plugins" / "one" / "skills" / "alpha"
    alpha.mkdir(parents=True)
    (alpha / "SKILL.md").write_bytes(_skill("alpha"))
    (alpha / "guide.md").write_text("guide\n", encoding="utf-8")
    (alpha / ".env").write_text("SECRET=not-a-bundle-file\n", encoding="utf-8")
    beta = root / "plugins" / "two" / "beta"
    beta.mkdir(parents=True)
    (beta / "SKILL.md").write_bytes(_skill("beta"))
    (root / "meta-plugins" / "skills" / "private").mkdir(parents=True)
    (root / "meta-plugins" / "skills" / "private" / "SKILL.md").write_bytes(_skill("private"))
    return root


def _write_policy_files(
    root: Path, *, gitignore: str | None = None, include: list[str] | None = None
) -> None:
    policy_dir = root / "tools" / "skill-tools"
    policy_dir.mkdir(parents=True, exist_ok=True)
    if gitignore is not None:
        (policy_dir / ".gitignore").write_text(gitignore, encoding="utf-8")
    if include is not None:
        body = (
            "include: []\n"
            if not include
            else "include:\n" + "".join(f"  - {pattern}\n" for pattern in include)
        )
        (policy_dir / ".skill-tools").write_text(body, encoding="utf-8")


def _install_fake_github(monkeypatch: pytest.MonkeyPatch, blobs: dict[str, bytes]) -> None:
    paths = tuple(sorted(PurePosixPath(name) for name in blobs))
    sha_by_path = {path: f"blob-{index}" for index, path in enumerate(paths)}

    def fake_request(self: GitHubSource, url: str):
        if "/commits/" in url:
            return {"sha": "commit-sha"}
        if "/git/trees/" in url:
            return {
                "truncated": False,
                "tree": [
                    {"type": "blob", "path": path.as_posix(), "sha": sha_by_path[path]}
                    for path in paths
                ],
            }
        sha = url.rsplit("/", 1)[-1]
        path = next(path for path in paths if sha_by_path[path] == sha)
        return {"encoding": "base64", "content": base64.b64encode(blobs[path.as_posix()]).decode()}

    monkeypatch.setattr(GitHubSource, "_request_json", fake_request)


def test_local_catalog_uses_both_layouts_and_excludes_unregistered_and_env(tmp_path: Path) -> None:
    root = make_repository(tmp_path / "source")
    source = LocalSource(root)
    records = discover_catalog(source)
    assert [
        (record.canonical_id, record.name, record.tool, record.plugin) for record in records
    ] == [
        ("plugins/one/skills/alpha/SKILL.md", "alpha", "Claude Code", "one"),
        ("plugins/two/beta/SKILL.md", "beta", "Cursor", "two"),
    ]
    assert records[0].files == (PurePosixPath("SKILL.md"), PurePosixPath("guide.md"))
    assert "# alpha" in records[0].body
    assert select_records(records, ["alpha", "plugins/two/beta/SKILL.md"]) == records
    listed = display_skill_path(records[0].canonical_id, source.descriptor)
    assert listed == str((root / "plugins" / "one" / "skills" / "alpha" / "SKILL.md").resolve())
    assert select_records(records, [listed], source_descriptor=source.descriptor) == (records[0],)
    assert "treeDigest" in source.fingerprint


def test_local_source_rejects_escape(tmp_path: Path) -> None:
    source = LocalSource(make_repository(tmp_path / "source"))
    with pytest.raises(SourceError, match="unsafe|escapes"):
        source.read_file(PurePosixPath("../secret"))


def test_local_source_walk_skips_dependency_and_cache_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without git, the walk must not descend into node_modules/.venv style trees."""

    root = make_repository(tmp_path / "source")
    for excluded in ("node_modules", ".venv", "__pycache__"):
        directory = root / "plugins" / "one" / excluded / "nested"
        directory.mkdir(parents=True)
        (directory / "payload.txt").write_text("ignored", encoding="utf-8")

    source = LocalSource(root)
    # Force the no-git fallback regardless of whether tmp_path happens to sit in a clone.
    monkeypatch.setattr(LocalSource, "_git_visible_files", lambda self: None)
    walked = source._visible_files()  # noqa: SLF001 - fallback walk is the behaviour under test

    assert PurePosixPath("plugins/one/skills/alpha/SKILL.md") in walked
    excluded_names = {"node_modules", ".venv", "__pycache__"}
    assert not [path for path in walked if excluded_names & set(path.parts)]


def test_duplicate_short_name_requires_canonical_id(tmp_path: Path) -> None:
    root = make_repository(tmp_path / "source")
    duplicate = root / "plugins" / "two" / "alpha"
    duplicate.mkdir(parents=True)
    (duplicate / "SKILL.md").write_bytes(_skill("alpha"))
    records = discover_catalog(LocalSource(root))
    with pytest.raises(CatalogError, match="ambiguous"):
        select_records(records, ["alpha"])


def test_github_catalog_matches_local_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = make_repository(tmp_path / "source")
    local_source = LocalSource(root)
    paths = local_source.list_files((PurePosixPath("plugins"), PurePosixPath("ai-tools.yaml")))
    blobs = {path: local_source.read_file(path) for path in paths}
    blobs[PurePosixPath("ai-tools.yaml")] = CATALOG.encode()
    paths = tuple(sorted(blobs))
    sha_by_path = {path: f"blob-{index}" for index, path in enumerate(paths)}

    def fake_request(self: GitHubSource, url: str):
        if "/commits/" in url:
            return {"sha": "commit-sha"}
        if "/git/trees/" in url:
            return {
                "truncated": False,
                "tree": [
                    {"type": "blob", "path": path.as_posix(), "sha": sha_by_path[path]}
                    for path in paths
                ],
            }
        sha = url.rsplit("/", 1)[-1]
        path = next(path for path, blob_sha in sha_by_path.items() if blob_sha == sha)
        return {"encoding": "base64", "content": base64.b64encode(blobs[path]).decode()}

    monkeypatch.setattr(GitHubSource, "_request_json", fake_request)
    remote = GitHubSource("owner", "repo", "main")
    assert discover_catalog(remote) == discover_catalog(local_source)
    assert remote.fingerprint["commit"] == "commit-sha"
    assert display_skill_path("plugins/one/skills/alpha/SKILL.md", remote.descriptor) == (
        "https://github.com/owner/repo/blob/commit-sha/plugins/one/skills/alpha/SKILL.md"
    )


def test_local_include_rescues_git_hidden_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repository(tmp_path / "source")
    _write_policy_files(root, include=[".env"])
    monkeypatch.setattr(LocalSource, "_git_visible_files", lambda self: None)
    walked = LocalSource(root)._visible_files()  # noqa: SLF001 - walk is the listing under test
    hidden = tuple(path for path in walked if path.name != ".env")
    monkeypatch.setattr(LocalSource, "_git_visible_files", lambda self: hidden)

    records = discover_catalog(LocalSource(root))
    assert PurePosixPath(".env") in records[0].files


def test_local_catalog_excludes_env_case_insensitively(tmp_path: Path) -> None:
    root = make_repository(tmp_path / "source")
    alpha = root / "plugins" / "one" / "skills" / "alpha"
    (alpha / ".ENV").write_text("SECRET=not-a-bundle-file\n", encoding="utf-8")
    records = discover_catalog(LocalSource(root))
    assert records[0].files == (PurePosixPath("SKILL.md"), PurePosixPath("guide.md"))


def test_gitignore_negation_restores_env_exclusion(tmp_path: Path) -> None:
    root = make_repository(tmp_path / "source")
    _write_policy_files(root, gitignore="!.env\n")
    records = discover_catalog(LocalSource(root))
    assert PurePosixPath(".env") in records[0].files


def test_include_does_not_rescue_pruned_directories(tmp_path: Path) -> None:
    root = make_repository(tmp_path / "source")
    nested = root / "plugins" / "one" / "skills" / "alpha" / "node_modules"
    nested.mkdir(parents=True)
    (nested / ".env").write_text("SECRET=not-a-bundle-file\n", encoding="utf-8")
    _write_policy_files(root, include=["node_modules/.env"])
    records = discover_catalog(LocalSource(root))
    assert records[0].files == (PurePosixPath("SKILL.md"), PurePosixPath("guide.md"))


def test_include_rescue_skips_symlinks(tmp_path: Path) -> None:
    root = make_repository(tmp_path / "source")
    alpha = root / "plugins" / "one" / "skills" / "alpha"
    target = alpha / "real-secret.txt"
    target.write_text("secret\n", encoding="utf-8")
    link = alpha / ".env"
    link.unlink()
    try:
        link.symlink_to(target.name)
    except OSError:
        pytest.skip("symlinks are not available on this platform")
    _write_policy_files(root, include=[".env"])

    records = discover_catalog(LocalSource(root))
    assert PurePosixPath(".env") not in records[0].files


def test_github_catalog_applies_excludes_and_include_to_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = {
        "ai-tools.yaml": CATALOG.encode(),
        "plugins/one/skills/alpha/SKILL.md": _skill("alpha"),
        "plugins/one/skills/alpha/.env": b"SECRET=tree-only\n",
        "plugins/two/beta/SKILL.md": _skill("beta"),
    }
    _install_fake_github(monkeypatch, base)
    remote = GitHubSource("owner", "repo", "main")
    assert discover_catalog(remote)[0].files == (PurePosixPath("SKILL.md"),)

    with_include = dict(base)
    with_include["tools/skill-tools/.skill-tools"] = b"include:\n  - .env\n"
    _install_fake_github(monkeypatch, with_include)
    remote = GitHubSource("owner", "repo", "main")
    # GitHub can only include files that exist in the tree; the include restores
    # the committed ``.env`` (no untracked rescue exists for remote sources).
    assert PurePosixPath(".env") in discover_catalog(remote)[0].files


def test_display_skill_path_uses_source_kind() -> None:
    github = display_skill_path(
        "plugins/one/skills/alpha/SKILL.md",
        {"type": "github", "owner": "fdshg693", "repository": "ai", "ref": "main"},
    )
    assert github == ("https://github.com/fdshg693/ai/blob/main/plugins/one/skills/alpha/SKILL.md")
    assert display_skill_path("plugins/one/skills/alpha/SKILL.md", None) == (
        "plugins/one/skills/alpha/SKILL.md"
    )


def _install_fake_github_repos(
    monkeypatch: pytest.MonkeyPatch,
    repos: dict[str, tuple[dict[str, bytes], dict[str, str]]],
) -> list[str]:
    """repos: "owner/repo" -> (blobs, gitlinks path -> commit sha). Returns requested URLs."""
    requested: list[str] = []
    blob_sha: dict[tuple[str, str], str] = {}
    blob_content: dict[str, bytes] = {}
    for name, (blobs, _links) in repos.items():
        for path, content in blobs.items():
            sha = f"blob{len(blob_content)}"
            blob_sha[(name, path)] = sha
            blob_content[sha] = content

    def fake_request(self: GitHubSource, url: str):
        requested.append(url)
        if "/commits/" in url:
            return {"sha": "commit-sha"}
        repo = url.split("/repos/", 1)[1].split("/git/", 1)[0]
        blobs, links = repos[repo]
        if "/git/trees/" in url:
            tree = [{"type": "blob", "path": p, "sha": blob_sha[(repo, p)]} for p in sorted(blobs)]
            tree += [{"type": "commit", "path": p, "sha": sha} for p, sha in links.items()]
            return {"truncated": False, "tree": tree}
        content = blob_content[url.rsplit("/", 1)[-1]]
        return {"encoding": "base64", "content": base64.b64encode(content).decode()}

    monkeypatch.setattr(GitHubSource, "_request_json", fake_request)
    return requested


def test_github_source_follows_submodules(monkeypatch: pytest.MonkeyPatch) -> None:
    gitmodules = (
        b'[submodule "plugins"]\n\tpath = plugins\n'
        b"\turl = https://github.com/owner/repo-plugins.git\n"
        b'[submodule "extra"]\n\tpath = extra\n\turl = ../repo-extra\n'
    )
    requested = _install_fake_github_repos(
        monkeypatch,
        {
            "owner/repo": (
                {"ai-tools.yaml": CATALOG.encode(), ".gitmodules": gitmodules},
                {"plugins": "plugins-sha", "extra": "extra-sha"},
            ),
            "owner/repo-plugins": (
                {
                    "one/skills/alpha/SKILL.md": _skill("alpha"),
                    "two/beta/SKILL.md": _skill("beta"),
                },
                {},
            ),
            "owner/repo-extra": ({"note.md": b"x\n"}, {}),
        },
    )
    remote = GitHubSource("owner", "repo", "main")
    assert remote.list_files((PurePosixPath("extra"),)) == (PurePosixPath("extra/note.md"),)
    records = discover_catalog(remote)
    assert sorted(record.name for record in records) == ["alpha", "beta"]
    assert remote.read_file(PurePosixPath("plugins/one/skills/alpha/SKILL.md")) == _skill("alpha")
    assert any("/repos/owner/repo-plugins/git/trees/plugins-sha" in url for url in requested)
    assert any("/repos/owner/repo-extra/git/trees/extra-sha" in url for url in requested)


@pytest.mark.parametrize(
    ("gitmodules", "message"),
    [
        (None, "no .gitmodules"),
        (b'[submodule "plugins"]\n\tpath = other\n\turl = ../x\n', "missing from .gitmodules"),
        (
            b'[submodule "plugins"]\n\tpath = plugins\n\turl = https://gitlab.com/o/r.git\n',
            "not on github.com",
        ),
    ],
)
def test_github_source_refuses_unresolvable_submodules(
    monkeypatch: pytest.MonkeyPatch, gitmodules: bytes | None, message: str
) -> None:
    blobs = {"ai-tools.yaml": CATALOG.encode()}
    if gitmodules is not None:
        blobs[".gitmodules"] = gitmodules
    _install_fake_github_repos(monkeypatch, {"owner/repo": (blobs, {"plugins": "sha"})})
    with pytest.raises(SourceError, match=message):
        GitHubSource("owner", "repo", "main")
