from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from vscode_profiles import wsl
from vscode_profiles.cli import main
from vscode_profiles.errors import CliError
from vscode_profiles.profiles import machine_profile


def _with_machine(
    tmp_path: Path, code_dir, monkeypatch: pytest.MonkeyPatch, machine_text: str | None
) -> tuple[Path, Path]:
    root = tmp_path / "Code"
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {
            None: '{\n  "claudeCode.a": true,\n  "claudeCode.b": "x"\n}\n',
            "py": '{\n  "claudeCode.a": true\n}\n',
        },
    )
    machine = tmp_path / "server" / "data" / "Machine" / "settings.json"
    machine.parent.mkdir(parents=True)
    if machine_text is not None:
        machine.write_text(machine_text, encoding="utf-8", newline="")

    def fake(distro: str):
        return machine_profile(f"WSL:{distro}", machine)

    monkeypatch.setattr("vscode_profiles.cli.wsl_machine_profile", fake)
    monkeypatch.setattr("vscode_profiles.apply.code_process_running", lambda: False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return root, machine


def test_list_and_diff_include_the_machine_pseudo_profile(
    tmp_path: Path, code_dir, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = _with_machine(tmp_path, code_dir, monkeypatch, '{ "claudeCode.a": true }\n')
    base = ["--user-data-dir", str(root), "--wsl", "Ubuntu-24.04"]
    assert main([*base, "list"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Default\town\t2",
        "Python\town\t1",
        "WSL:Ubuntu-24.04\tmachine\t1",
    ]
    assert main([*base, "diff", "--by-profile"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        'claudeCode.a\tsame\t{"Default": 1, "Python": 1, "WSL:Ubuntu-24.04": 1}',
        'claudeCode.b\tmissing\t{"Default": 1, "Python": null, "WSL:Ubuntu-24.04": null}',
    ]


def test_apply_to_machine_keeps_lf_and_backs_up(
    tmp_path: Path, code_dir, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, machine = _with_machine(tmp_path, code_dir, monkeypatch, '{\n  "claudeCode.a": true\n}\n')
    code = main(
        [
            "--user-data-dir",
            str(root),
            "--wsl",
            "Ubuntu-24.04",
            "apply",
            "--from",
            "Default",
            "--to",
            "WSL:Ubuntu-24.04",
            "--key",
            "claudeCode.b",
            "--write",
        ]
    )
    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[0] == 'WSL:Ubuntu-24.04\tclaudeCode.b\tadd\t"x"'
    assert out[1].startswith("backup\tWSL:Ubuntu-24.04\t")
    assert "_machine" in out[1] and "WSL_Ubuntu-24.04" in out[1]
    assert machine.read_bytes() == b'{\n  "claudeCode.a": true,\n  "claudeCode.b": "x"\n}\n'


def test_missing_machine_settings_is_empty_and_created_on_write(
    tmp_path: Path, code_dir, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, machine = _with_machine(tmp_path, code_dir, monkeypatch, None)
    base = ["--user-data-dir", str(root), "--wsl", "Ubuntu-24.04"]
    assert main([*base, "list"]) == 0
    assert "WSL:Ubuntu-24.04\tmachine\t0" in capsys.readouterr().out
    args = ["apply", "--from", "Default", "--to", "all", "--key", "claudeCode.a", "--write"]
    assert main([*base, *args]) == 0
    assert machine.read_text(encoding="utf-8") == '{\n  "claudeCode.a": true\n}\n'


@pytest.mark.skipif(sys.platform != "win32", reason="UNC paths are Windows-only")
def test_machine_settings_path_builds_a_wsl_unc_path() -> None:
    path = wsl.machine_settings_path("Ubuntu-24.04", "/home/me")
    assert str(path) == (
        r"\\wsl.localhost\Ubuntu-24.04\home\me\.vscode-server\data\Machine\settings.json"
    )


def test_machine_settings_path_rejects_relative_home() -> None:
    with pytest.raises(CliError):
        wsl.machine_settings_path("Ubuntu-24.04", "relative")


def test_wsl_home_reads_stdout_and_reports_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def ok(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b"/home/me", stderr=b"")

    monkeypatch.setattr(wsl.subprocess, "run", ok)
    assert wsl.wsl_home("Ubuntu-24.04") == "/home/me"
    assert calls[0][:3] == ["wsl.exe", "-d", "Ubuntu-24.04"]

    def bad(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"")

    monkeypatch.setattr(wsl.subprocess, "run", bad)
    with pytest.raises(CliError):
        wsl.wsl_home("Nope")


def test_wsl_option_rejects_bad_names_and_other_platforms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wsl.platform, "system", lambda: "Windows")
    with pytest.raises(CliError) as bad_name:
        wsl.wsl_machine_profile("..\\x")
    assert bad_name.value.code == 2
    monkeypatch.setattr(wsl.platform, "system", lambda: "Linux")
    with pytest.raises(CliError) as other:
        wsl.wsl_machine_profile("Ubuntu-24.04")
    assert other.value.code == 2
