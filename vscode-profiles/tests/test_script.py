from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vscode_profiles.cli import main
from vscode_profiles.script import ps_quote


def _sample(root: Path, code_dir) -> None:
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: '{ "a": 1, "b": 2 }\n', "py": '{ "a": 1, "b": 3 }\n'},
    )


def test_ps_quote_doubles_single_quotes() -> None:
    assert ps_quote("it's") == "'it''s'"


def test_emit_ps1_writes_header_then_appends_commands(
    tmp_path: Path,
    code_dir,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("vscode_profiles.apply.code_process_running", lambda: True)
    root = tmp_path / "Code"
    _sample(root, code_dir)
    before = (root / "User" / "profiles" / "py" / "settings.json").read_bytes()
    script = tmp_path / "out" / ".." / "apply.ps1"
    (tmp_path / "out").mkdir()
    base = ["--user-data-dir", str(root)]
    first = [*base, "apply", "--from", "Default", "--to", "all", "--key", "b", "--mask"]
    assert main([*first, "--emit-ps1", str(script)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Python\tb\treplace\t2\t3"
    assert out[-1] == f"script\t{script.resolve()}"

    second = [*base, "remove", "--profile", "Python", "--key", "a"]
    assert main([*second, "--emit-ps1", str(script)]) == 0
    capsys.readouterr()

    raw = script.resolve().read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.count(b"\xef\xbb\xbf") == 1
    text = raw.decode("utf-8-sig")
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")
    assert text.count("Get-Process -Name Code") == 1
    commands = [line for line in text.splitlines() if line.startswith("& ")]
    assert commands == [
        "& "
        + " ".join(
            ps_quote(part)
            for part in [
                sys.executable,
                "-m",
                "vscode_profiles",
                "--user-data-dir",
                str(root.resolve()),
                "apply",
                "--from",
                "Default",
                "--to",
                "all",
                "--key",
                "b",
                "--mask",
                "--write",
            ]
        ),
        "& "
        + " ".join(
            ps_quote(part)
            for part in [
                sys.executable,
                "-m",
                "vscode_profiles",
                "--user-data-dir",
                str(root.resolve()),
                "remove",
                "--profile",
                "Python",
                "--key",
                "a",
                "--write",
            ]
        ),
    ]
    assert "--force" not in text
    assert (root / "User" / "profiles" / "py" / "settings.json").read_bytes() == before


def test_emit_ps1_without_changes_leaves_no_script(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    script = tmp_path / "apply.ps1"
    args = ["--user-data-dir", str(root), "apply", "--from", "Default", "--to", "all"]
    assert main([*args, "--key", "a", "--emit-ps1", str(script)]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["Python\ta\tsame\t1"]
    assert "nothing to write" in captured.err
    assert not script.exists()


def test_emit_ps1_and_write_are_exclusive(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    script = tmp_path / "apply.ps1"
    args = ["--user-data-dir", str(root), "apply", "--from", "Default", "--to", "all"]
    assert main([*args, "--key", "b", "--write", "--emit-ps1", str(script)]) == 2
    assert "--emit-ps1" in capsys.readouterr().err
    assert not script.exists()
