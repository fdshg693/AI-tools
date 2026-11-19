"""``--parallel`` のファンアウトと CLI 分岐。API はモックする。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from aim_cli import DEFAULT_MODEL, MODELS, AimError, main
from aim_parallel import (
    ask_once_async,
    format_json,
    format_markdown,
    make_entry,
    run_parallel,
)


class DummyClient:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["aim", *argv])
    try:
        main()
    except SystemExit as exc:
        return exc.code if exc.code is not None else 0
    return 0


def _fail_api(*_args, **_kwargs):
    raise AssertionError("APIを叩いてはならない")


def test_format_markdown_and_json() -> None:
    entries = [
        make_entry("a.py", "/abs/a.py", success=True, response="ok-a", index=1, prompt="@a.py"),
        make_entry("b.py", "/abs/b.py", success=False, error="boom", index=2, prompt="@b.py"),
    ]
    md = format_markdown(entries)
    assert md.startswith("## 1 · a.py")
    assert "ok-a" in md
    assert "## 2 · b.py" in md
    assert "⚠ エラー: boom" in md
    parsed = json.loads(format_json(entries))
    assert parsed[0]["path"] == "a.py"
    assert parsed[0]["index"] == 1
    assert parsed[0]["success"] is True
    assert parsed[1]["success"] is False
    assert parsed[1]["error"] == "boom"


def test_ask_once_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def fake_call(*_args, **_kwargs) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise AimError("once")
        return "  recovered  "

    monkeypatch.setattr("aim_parallel.call_async", fake_call)
    success, result = asyncio.run(ask_once_async(DummyClient(), "model", "MESSAGE"))
    assert success is True
    assert result == "recovered"
    assert calls["n"] == 2


def test_ask_once_gives_up_after_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call(*_args, **_kwargs) -> str:
        raise AimError("always")

    monkeypatch.setattr("aim_parallel.call_async", fake_call)
    success, result = asyncio.run(ask_once_async(DummyClient(), "model", "MESSAGE"))
    assert success is False
    assert "always" in result


def test_run_parallel_keeps_order_and_sends_each_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    async def fake_call(_client, _model_id, prompt, **kwargs) -> str:
        trace = kwargs.get("trace")
        assert isinstance(trace, dict)
        seen.append((prompt, trace))
        if prompt == "msg-a":
            return "resp-a"
        return "resp-b"

    monkeypatch.setattr("aim_parallel.call_async", fake_call)
    monkeypatch.setattr("aim_parallel.create_client", lambda: DummyClient())

    entries = [
        make_entry("a.py", "/a.py", success=False, error="pending", index=1, prompt="@a.py"),
        make_entry("b.py", "/b.py", success=False, error="pending", index=2, prompt="@b.py"),
    ]
    targets = [(0, "msg-a"), (1, "msg-b")]
    out = run_parallel("model-id", 2, entries, targets, web=True)
    assert [entry["response"] for entry in out] == ["resp-a", "resp-b"]
    assert all(entry["success"] for entry in out)
    by_path = {trace["file_path"]: prompt for prompt, trace in seen}
    assert by_path == {"a.py": "msg-a", "b.py": "msg-b"}
    assert all(trace["tool"] == "aim-cli" for _, trace in seen)
    assert {trace["prompt_index"] for _, trace in seen} == {"1", "2"}


def test_jobs_without_parallel_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("aim_cli.call", _fail_api)
    monkeypatch.setattr("aim_cli.create_client", _fail_api)
    code = _run_main(monkeypatch, ["--jobs", "2", "--prompt", "hi"])
    assert code == 1
    assert "--parallel" in capsys.readouterr().err


def test_multiple_prompts_without_parallel_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("aim_cli.call", _fail_api)
    monkeypatch.setattr("aim_cli.create_client", _fail_api)
    code = _run_main(monkeypatch, ["--prompt", "a", "b"])
    assert code == 1
    assert "--parallel" in capsys.readouterr().err


def test_jobs_out_of_range_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("aim_cli.call", _fail_api)
    code = _run_main(monkeypatch, ["--parallel", "--jobs", "0", "--prompt", "@a.py 要約"])
    assert code == 1
    assert "1〜10" in capsys.readouterr().err


def test_parallel_plain_prompts_do_not_need_at_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    async def fake_call(_client, _model_id, prompt, **kwargs):
        trace = kwargs.get("trace")
        assert isinstance(trace, dict)
        seen.append((prompt, trace))
        return f"resp-{prompt}"

    monkeypatch.setattr("aim_parallel.call_async", fake_call)
    monkeypatch.setattr("aim_parallel.create_client", lambda: DummyClient())
    code = _run_main(monkeypatch, ["--parallel", "--prompt", "質問A", "質問B"])
    assert code == 0
    by_prompt = {prompt: trace for prompt, trace in seen}
    assert set(by_prompt) == {"質問A", "質問B"}
    assert by_prompt["質問A"] == {"tool": "aim-cli", "prompt_index": "1"}
    assert by_prompt["質問B"] == {"tool": "aim-cli", "prompt_index": "2"}
    out = capsys.readouterr().out
    assert "## 1" in out
    assert "## 2" in out
    assert "resp-質問A" in out
    assert "resp-質問B" in out


def test_format_json_single_shot_is_one_element_array(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("aim_cli.create_client", lambda: DummyClient())
    monkeypatch.setattr("aim_cli.call", lambda *_a, **_k: "ok")
    code = _run_main(monkeypatch, ["--format", "json", "--prompt", "hi"])
    assert code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["success"] is True
    assert parsed[0]["response"] == "ok"
    assert parsed[0]["path"] == ""
    assert parsed[0]["index"] == 1
    assert parsed[0]["prompt"] == "hi"


def test_single_shot_expands_at_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "foo.py").write_text("hello-content", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    seen: dict[str, object] = {}

    def fake_call(_client, model_id, prompt, **kwargs):
        seen["model_id"] = model_id
        seen["prompt"] = prompt
        seen["web"] = kwargs.get("web")
        seen["trace"] = kwargs.get("trace")
        return "ok"

    monkeypatch.setattr("aim_cli.create_client", lambda: DummyClient())
    monkeypatch.setattr("aim_cli.call", fake_call)
    code = _run_main(monkeypatch, ["--web", "--prompt", "@foo.pyを要約して"])
    assert code == 0
    assert capsys.readouterr().out == "ok\n"
    prompt = seen["prompt"]
    assert isinstance(prompt, str)
    assert "hello-content" in prompt
    assert "--- FILE: foo.py ---" in prompt
    assert prompt.endswith("を要約して")
    assert seen["web"] is True
    assert seen["trace"] == {"tool": "aim-cli"}
    assert seen["model_id"] == MODELS[DEFAULT_MODEL]


def test_single_shot_missing_path_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aim_cli.call", _fail_api)
    code = _run_main(monkeypatch, ["--prompt", "@src/nope.py を要約"])
    assert code == 1
    assert "存在しません" in capsys.readouterr().err


def test_single_shot_read_failure_exits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "x.bin").write_bytes(b"\x00\x01")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aim_cli.call", _fail_api)
    code = _run_main(monkeypatch, ["--prompt", "@x.bin を見て"])
    assert code == 1
    assert "バイナリ" in capsys.readouterr().err


def test_parallel_cli_markdown_and_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "a.py").write_text("AAA", encoding="utf-8")
    (tmp_path / "b.py").write_text("BBB", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    async def fake_call(_client, _model_id, prompt, **kwargs):
        if "AAA" in prompt:
            raise AimError("nope")
        assert kwargs.get("web") is False
        assert kwargs.get("trace") == {
            "tool": "aim-cli",
            "prompt_index": "2",
            "file_path": "b.py",
        }
        return "resp-b"

    monkeypatch.setattr("aim_parallel.call_async", fake_call)
    monkeypatch.setattr("aim_parallel.create_client", lambda: DummyClient())
    monkeypatch.setattr("aim_cli.call", _fail_api)
    code = _run_main(
        monkeypatch,
        ["--parallel", "--prompt", "@a.py を見て", "@b.py を見て"],
    )
    assert code == 0
    captured = capsys.readouterr()
    out = captured.out
    assert "## 1 · a.py" in out
    assert "## 2 · b.py" in out
    assert "⚠ エラー:" in out
    assert "resp-b" in out
    assert "注意:" not in captured.err


def test_parallel_repeated_prompt_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "a.py").write_text("AAA", encoding="utf-8")
    (tmp_path / "b.py").write_text("BBB", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    seen: list[str] = []

    async def fake_call(_client, _model_id, prompt, **_kwargs):
        seen.append(prompt)
        return "ok"

    monkeypatch.setattr("aim_parallel.call_async", fake_call)
    monkeypatch.setattr("aim_parallel.create_client", lambda: DummyClient())
    code = _run_main(
        monkeypatch,
        [
            "--parallel",
            "--prompt",
            "@a.py 要約して",
            "--prompt",
            "@b.py 要約して",
        ],
    )
    assert code == 0
    assert len(seen) == 2
    by_body = {("AAA" in p, "BBB" in p): p for p in seen}
    assert (True, False) in by_body
    assert (False, True) in by_body
    assert by_body[(True, False)].endswith("要約して")
    assert by_body[(False, True)].endswith("要約して")


def test_parallel_one_prompt_with_many_at_paths_warns_and_is_one_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "a.py").write_text("AAA", encoding="utf-8")
    (tmp_path / "b.py").write_text("BBB", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    seen: list[str] = []

    async def fake_call(_client, _model_id, prompt, **_kwargs):
        seen.append(prompt)
        return "one"

    monkeypatch.setattr("aim_parallel.call_async", fake_call)
    monkeypatch.setattr("aim_parallel.create_client", lambda: DummyClient())
    code = _run_main(
        monkeypatch,
        ["--parallel", "--prompt", "@a.py @b.py を見て"],
    )
    assert code == 0
    assert len(seen) == 1
    assert "AAA" in seen[0]
    assert "BBB" in seen[0]
    captured = capsys.readouterr()
    assert "注意:" in captured.err
    assert "## 1 · a.py" in captured.out
    assert "one" in captured.out


def test_parallel_cli_json_format(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "a.py").write_text("AAA", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    async def fake_call(_client, _model_id, prompt, **kwargs):
        assert kwargs.get("web") is True
        assert "共通" in prompt
        assert "AAA" in prompt
        return "resp-a"

    monkeypatch.setattr("aim_parallel.call_async", fake_call)
    monkeypatch.setattr("aim_parallel.create_client", lambda: DummyClient())
    code = _run_main(
        monkeypatch,
        [
            "--parallel",
            "--web",
            "--format",
            "json",
            "--prompt",
            "共通 @a.py",
        ],
    )
    assert code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert len(parsed) == 1
    assert parsed[0]["path"] == "a.py"
    assert parsed[0]["index"] == 1
    assert parsed[0]["prompt"] == "共通 @a.py"
    assert parsed[0]["success"] is True
    assert parsed[0]["response"] == "resp-a"
    assert parsed[0]["error"] is None


def test_help_mentions_new_flags(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run_main(monkeypatch, ["--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "--parallel" in out
    assert "--jobs" in out
    assert "--format" in out
    assert "--full-content-names" in out
    assert "@path" in out or "@src/foo.py" in out
    assert "@a.py 要約して" in out
