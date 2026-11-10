from __future__ import annotations

from pathlib import Path

from issue_agent import dispatch, github_ops, worker, worktree
from issue_agent.config import Config

ISSUE = {
    "number": 7,
    "title": "テストISSUE",
    "body": "本文",
    "labels": [{"name": "tool:claude-code"}],
}
SUCCESS_INVOCATION = dispatch.AgentInvocation(
    subtype="success", session_id="sess-1", last_text="done"
)


def _config() -> Config:
    return Config(owner="o", repo="r")


def _patch_common(monkeypatch, *, invocation=SUCCESS_INVOCATION, workdir=Path("/tmp/issue-7")):
    monkeypatch.setattr(github_ops, "get_issue", lambda owner, repo, number: ISSUE)
    monkeypatch.setattr(dispatch, "resolve_tool_label", lambda labels: "tool:claude-code")
    monkeypatch.setattr(dispatch, "resolve_model_label", lambda labels: "sonnet")
    monkeypatch.setattr(dispatch, "resolve_handler", lambda tool_label: lambda **kwargs: invocation)
    monkeypatch.setattr(worktree, "create", lambda issue_number: workdir)
    monkeypatch.setattr(worker, "_rev_parse_head", lambda workdir: "base-sha")
    comments: list[str] = []
    monkeypatch.setattr(
        github_ops,
        "create_issue_comment",
        lambda owner, repo, number, body: comments.append(body),
    )
    cleanups: list[tuple[Path, bool]] = []
    monkeypatch.setattr(worktree, "cleanup", lambda path, *, keep: cleanups.append((path, keep)))
    return comments, cleanups


def test_run_worker_succeeds_when_pr_exists(monkeypatch) -> None:
    comments, cleanups = _patch_common(monkeypatch)
    monkeypatch.setattr(worker, "_commit_count", lambda workdir, base_sha: 2)
    monkeypatch.setattr(
        github_ops,
        "get_pr_for_branch",
        lambda owner, repo, branch: {"url": "https://github.com/o/r/pull/9", "number": 9},
    )

    result = worker.run_worker(_config(), 7)

    assert result["success"] is True
    assert result["pr_url"] == "https://github.com/o/r/pull/9"
    assert result["commit_count"] == 2
    assert "https://github.com/o/r/pull/9" in comments[0]
    assert cleanups == [(Path("/tmp/issue-7"), False)]


def test_run_worker_fails_when_commits_but_no_pr(monkeypatch) -> None:
    comments, cleanups = _patch_common(monkeypatch)
    monkeypatch.setattr(worker, "_commit_count", lambda workdir, base_sha: 3)
    monkeypatch.setattr(github_ops, "get_pr_for_branch", lambda owner, repo, branch: None)

    result = worker.run_worker(_config(), 7)

    assert result["success"] is False
    assert "PRが作成されませんでした" in result["detail"]
    assert cleanups == [(Path("/tmp/issue-7"), True)]
    assert len(comments) == 1


def test_run_worker_fails_when_no_commits(monkeypatch) -> None:
    _patch_common(monkeypatch)
    monkeypatch.setattr(worker, "_commit_count", lambda workdir, base_sha: 0)
    monkeypatch.setattr(github_ops, "get_pr_for_branch", lambda owner, repo, branch: None)

    result = worker.run_worker(_config(), 7)

    assert result["success"] is False
    assert "変更がコミットされませんでした" in result["detail"]


def test_run_worker_fails_when_agent_subtype_not_success(monkeypatch) -> None:
    invocation = dispatch.AgentInvocation(
        subtype="error_max_turns", session_id="sess-2", last_text=""
    )
    comments, cleanups = _patch_common(monkeypatch, invocation=invocation)
    called = []
    monkeypatch.setattr(
        github_ops, "get_pr_for_branch", lambda owner, repo, branch: called.append(1)
    )

    result = worker.run_worker(_config(), 7)

    assert result["success"] is False
    assert "異常終了" in result["detail"]
    assert called == []  # PR確認まで進まない
    assert cleanups == [(Path("/tmp/issue-7"), True)]


def test_run_worker_reports_and_skips_cleanup_when_dispatch_fails_before_worktree(
    monkeypatch,
) -> None:
    monkeypatch.setattr(github_ops, "get_issue", lambda owner, repo, number: ISSUE)
    monkeypatch.setattr(
        dispatch,
        "resolve_tool_label",
        lambda labels: (_ for _ in ()).throw(dispatch.DispatchError("no tool label")),
    )
    comments: list[str] = []
    monkeypatch.setattr(
        github_ops,
        "create_issue_comment",
        lambda owner, repo, number, body: comments.append(body),
    )
    cleanups: list[tuple[Path, bool]] = []
    monkeypatch.setattr(worktree, "cleanup", lambda path, *, keep: cleanups.append((path, keep)))

    result = worker.run_worker(_config(), 7)

    assert result["success"] is False
    assert result["detail"] == "no tool label"
    assert cleanups == []  # workdirが作られていないので後片付けは呼ばれない
    assert "作業ブランチ" not in comments[0]
