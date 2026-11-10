from __future__ import annotations

from pathlib import Path

from issue_agent import worktree


def test_cleanup_removes_when_not_keeping(monkeypatch) -> None:
    removed: list[Path] = []
    monkeypatch.setattr(worktree, "remove", lambda path: removed.append(path))

    path = Path("/tmp/issue-1")
    worktree.cleanup(path, keep=False)

    assert removed == [path]


def test_cleanup_keeps_without_removing(monkeypatch) -> None:
    removed: list[Path] = []
    monkeypatch.setattr(worktree, "remove", lambda path: removed.append(path))

    worktree.cleanup(Path("/tmp/issue-1"), keep=True)

    assert removed == []
