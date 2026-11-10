from __future__ import annotations

from pathlib import Path

from issue_agent.attempt_store import AttemptStore, resolve_db_path


def make_store(tmp_path: Path) -> AttemptStore:
    return AttemptStore(tmp_path / "state.db")


def test_record_attempt_start_first_time_returns_true(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert store.record_attempt_start(1) is True


def test_record_attempt_start_second_time_returns_false(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.record_attempt_start(1)
    assert store.record_attempt_start(1) is False


def test_record_attempt_result_updates_fields(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.record_attempt_start(1)
    store.record_attempt_result(1, success=True, detail="ok", log_file="issues/1.log")

    attempt = store.get_attempt(1)
    assert attempt["success"] == 1
    assert attempt["detail"] == "ok"
    assert attempt["log_file"] == "issues/1.log"
    assert attempt["finished_at"] is not None


def test_get_attempt_missing_returns_none(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert store.get_attempt(999) is None


def test_reset_removes_record_and_allows_retry(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.record_attempt_start(1)

    assert store.reset(1) is True
    assert store.get_attempt(1) is None
    assert store.record_attempt_start(1) is True


def test_reset_missing_record_returns_false(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert store.reset(999) is False


def test_resolve_db_path_relative_is_under_issue_agent_root() -> None:
    resolved = resolve_db_path("data/state.db")
    assert resolved.parts[-2:] == ("data", "state.db")
    assert resolved.is_absolute()


def test_resolve_db_path_absolute_is_unchanged(tmp_path: Path) -> None:
    absolute = tmp_path / "elsewhere" / "state.db"
    assert resolve_db_path(str(absolute)) == absolute
