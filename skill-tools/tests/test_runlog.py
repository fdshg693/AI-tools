from __future__ import annotations

import json
from pathlib import Path

from skill_tools.cli import main
from skill_tools.runlog import SessionLog


def _record(log: SessionLog, cwd: Path, *, stdout: str = "", stderr: str = "") -> None:
    log.record(
        argv=["list-skills"],
        cwd=cwd,
        started="2026-09-23T00:00:00.000Z",
        ended="2026-09-23T00:00:01.000Z",
        exit_code=0,
        stdout=stdout,
        stderr=stderr,
    )


def test_record_writes_paired_input_and_output(tmp_path: Path) -> None:
    log = SessionLog(directory=tmp_path / "logs", max_bytes=1_000_000)
    _record(log, tmp_path, stdout="alpha\n", stderr="warning: x\n")

    input_file = tmp_path / "logs" / "input" / "0001.log"
    output_file = tmp_path / "logs" / "output" / "0001.log"
    input_text = input_file.read_text(encoding="utf-8")
    output_text = output_file.read_text(encoding="utf-8")

    assert "run 000001" in input_text
    assert f"cwd: {tmp_path}" in input_text
    assert "[stdout]\nalpha" in output_text
    assert "[stderr]\nwarning: x" in output_text
    assert "exit 0" in output_text
    assert "run 000001" in output_text


def test_run_ids_stay_in_sync_across_pairs(tmp_path: Path) -> None:
    log = SessionLog(directory=tmp_path / "logs", max_bytes=120)
    for _ in range(4):
        _record(log, tmp_path, stdout="x" * 40)

    input_files = sorted((tmp_path / "logs" / "input").glob("*.log"))
    output_files = sorted((tmp_path / "logs" / "output").glob("*.log"))
    assert [p.name for p in input_files] == [p.name for p in output_files]
    assert len(input_files) > 1

    state = json.loads((tmp_path / "logs" / ".state.json").read_text(encoding="utf-8"))
    assert state["run"] == 4
    assert state["pair"] == len(input_files)


def test_rotation_keeps_items_whole(tmp_path: Path) -> None:
    log = SessionLog(directory=tmp_path / "logs", max_bytes=200)
    for _ in range(5):
        _record(log, tmp_path, stdout="y" * 10)

    output_files = sorted((tmp_path / "logs" / "output").glob("*.log"))
    assert len(output_files) > 1
    for path in output_files:
        text = path.read_text(encoding="utf-8")
        assert text.count("===== run") == text.count("[stdout]")
        if path != output_files[-1]:
            assert path.stat().st_size <= 200


def test_single_item_may_exceed_threshold(tmp_path: Path) -> None:
    log = SessionLog(directory=tmp_path / "logs", max_bytes=10)
    _record(log, tmp_path, stdout="z" * 500)

    output_file = tmp_path / "logs" / "output" / "0001.log"
    assert output_file.stat().st_size > 10


def test_from_environment_reads_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SKILL_TOOLS_LOG_DIR", str(tmp_path / "custom"))
    monkeypatch.setenv("SKILL_TOOLS_LOG_MAX_BYTES", "1234")
    log = SessionLog.from_environment()
    assert log is not None
    assert log.directory == tmp_path / "custom"
    assert log.max_bytes == 1234

    monkeypatch.setenv("SKILL_TOOLS_LOG_DISABLE", "true")
    assert SessionLog.from_environment() is None


def test_cli_records_input_and_output(
    tmp_path: Path, monkeypatch, capsys, make_repo, write_config
) -> None:
    log_dir = tmp_path / "cli-logs"
    monkeypatch.setenv("SKILL_TOOLS_LOG_DIR", str(log_dir))
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")

    assert main(["list-skills", "--config", str(config)], cwd=tmp_path) == 0
    capsys.readouterr()

    input_text = (log_dir / "input" / "0001.log").read_text(encoding="utf-8")
    output_text = (log_dir / "output" / "0001.log").read_text(encoding="utf-8")
    assert f"cwd: {tmp_path}" in input_text
    assert '"list-skills"' in input_text
    assert "alpha" in output_text


def test_cli_redacts_search_snippets_from_runlog(
    tmp_path: Path, monkeypatch, capsys, make_repo, write_config, embedder
) -> None:
    log_dir = tmp_path / "cli-logs"
    monkeypatch.setenv("SKILL_TOOLS_LOG_DIR", str(log_dir))
    source = make_repo(tmp_path / "source")
    skill = source / "plugins" / "one" / "skills" / "alpha" / "SKILL.md"
    skill.write_text(
        "---\nname: alpha\ndescription: alpha\n---\n\nprivate-index-only phrase\n",
        encoding="utf-8",
    )
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")
    assert main(["build-index", "--config", str(config)], cwd=tmp_path, embedder=embedder) == 0
    capsys.readouterr()

    assert (
        main(
            ["search", "--config", str(config), "--query", "private-index-only", "--json"],
            cwd=tmp_path,
            embedder=embedder,
        )
        == 0
    )
    visible = capsys.readouterr().out
    output_text = (log_dir / "output" / "0001.log").read_text(encoding="utf-8")

    assert "private-index-only" in visible
    assert "private-index-only" not in output_text
    assert "search output redacted" in output_text


def test_cli_redacts_fb_text_from_runlog(
    tmp_path: Path, monkeypatch, capsys, make_repo, write_config
) -> None:
    log_dir = tmp_path / "cli-logs"
    fb_dir = tmp_path / "fb"
    monkeypatch.setenv("SKILL_TOOLS_LOG_DIR", str(log_dir))
    monkeypatch.setenv("SKILL_TOOLS_FB_DIR", str(fb_dir))
    source = make_repo(tmp_path / "source")
    config = write_config(tmp_path / "cfg.yaml", source, tmp_path / "index.json")

    assert (
        main(
            ["--config", str(config), "--fb", "alpha", "--fb-text", "secret feedback body"],
            cwd=tmp_path,
        )
        == 0
    )
    capsys.readouterr()
    input_text = (log_dir / "input" / "0001.log").read_text(encoding="utf-8")

    assert "secret feedback body" not in input_text
    assert "[fb text redacted]" in input_text
