from __future__ import annotations

import json

import pytest

from issue_agent import github_ops


class _FakeCompletedProcess:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_get_pr_for_branch_returns_first_match(monkeypatch) -> None:
    prs = [{"url": "https://github.com/o/r/pull/1", "number": 1, "state": "OPEN"}]

    def fake_run(args, **kwargs):
        assert args[:3] == ["gh", "pr", "list"]
        assert "--head" in args
        assert args[args.index("--head") + 1] == "issue-agent/issue-42"
        return _FakeCompletedProcess(json.dumps(prs))

    monkeypatch.setattr(github_ops.subprocess, "run", fake_run)

    pr = github_ops.get_pr_for_branch("o", "r", "issue-agent/issue-42")

    assert pr == prs[0]


def test_get_pr_for_branch_returns_none_when_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        github_ops.subprocess, "run", lambda args, **kwargs: _FakeCompletedProcess("[]")
    )

    assert github_ops.get_pr_for_branch("o", "r", "issue-agent/issue-42") is None


def test_get_pr_for_branch_raises_on_gh_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        github_ops.subprocess,
        "run",
        lambda args, **kwargs: _FakeCompletedProcess("", returncode=1, stderr="boom"),
    )

    with pytest.raises(github_ops.GitHubOpsError):
        github_ops.get_pr_for_branch("o", "r", "issue-agent/issue-42")
