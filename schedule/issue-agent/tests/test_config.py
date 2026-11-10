from __future__ import annotations

from issue_agent.config import Config


def test_from_env_defaults_when_nothing_set(monkeypatch) -> None:
    for name in [
        "ISSUE_AGENT_OWNER",
        "ISSUE_AGENT_REPO",
        "ISSUE_AGENT_TOOL_LABELS",
        "ISSUE_AGENT_SUPPORTED_TOOL_LABELS",
        "ISSUE_AGENT_ALLOWED_LOGINS",
        "ISSUE_AGENT_MAX_ISSUES_PER_CYCLE",
        "ISSUE_AGENT_WORKER_TIMEOUT_SECONDS",
        "ISSUE_AGENT_STATE_DB_PATH",
        "ISSUE_AGENT_LOG_DIR",
    ]:
        monkeypatch.delenv(name, raising=False)

    config = Config.from_env()

    assert config.owner == "fdshg693"
    assert config.repo == "AI"
    assert config.tracked_tool_labels == ("tool:claude-code",)
    assert config.supported_tool_labels == frozenset({"tool:claude-code"})
    assert config.allowed_logins is None
    assert config.max_issues_per_cycle == 1
    assert config.worker_timeout_seconds == 1200
    assert config.state_db_path == "data/state.db"
    assert config.log_dir == "data/logs"


def test_from_env_blank_string_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("ISSUE_AGENT_OWNER", "   ")
    monkeypatch.setenv("ISSUE_AGENT_MAX_ISSUES_PER_CYCLE", "")

    config = Config.from_env()

    assert config.owner == "fdshg693"
    assert config.max_issues_per_cycle == 1


def test_from_env_reads_overrides(monkeypatch) -> None:
    monkeypatch.setenv("ISSUE_AGENT_OWNER", "someone")
    monkeypatch.setenv("ISSUE_AGENT_REPO", "somerepo")
    monkeypatch.setenv("ISSUE_AGENT_TOOL_LABELS", "tool:claude-code, tool:codex")
    monkeypatch.setenv("ISSUE_AGENT_SUPPORTED_TOOL_LABELS", "tool:claude-code")
    monkeypatch.setenv("ISSUE_AGENT_MAX_ISSUES_PER_CYCLE", "3")
    monkeypatch.setenv("ISSUE_AGENT_WORKER_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("ISSUE_AGENT_STATE_DB_PATH", "custom/state.db")
    monkeypatch.setenv("ISSUE_AGENT_LOG_DIR", "custom/logs")

    config = Config.from_env()

    assert config.owner == "someone"
    assert config.repo == "somerepo"
    assert config.tracked_tool_labels == ("tool:claude-code", "tool:codex")
    assert config.supported_tool_labels == frozenset({"tool:claude-code"})
    assert config.max_issues_per_cycle == 3
    assert config.worker_timeout_seconds == 60
    assert config.state_db_path == "custom/state.db"
    assert config.log_dir == "custom/logs"


def test_from_env_allowed_logins_unset_is_none(monkeypatch) -> None:
    monkeypatch.delenv("ISSUE_AGENT_ALLOWED_LOGINS", raising=False)

    assert Config.from_env().allowed_logins is None


def test_from_env_allowed_logins_parses_csv(monkeypatch) -> None:
    monkeypatch.setenv("ISSUE_AGENT_ALLOWED_LOGINS", "alice, bob")

    assert Config.from_env().allowed_logins == frozenset({"alice", "bob"})
