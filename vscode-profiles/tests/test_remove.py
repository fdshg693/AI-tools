from __future__ import annotations

from pathlib import Path

import pytest

from vscode_profiles.apply import remove_settings_keys
from vscode_profiles.cli import main
from vscode_profiles.jsonc import loads


def _settings(root: Path, location: str | None) -> Path:
    if location is None:
        return root / "User" / "settings.json"
    return root / "User" / "profiles" / Path(location) / "settings.json"


def test_remove_middle_key_keeps_comments_and_other_keys() -> None:
    text = """{
  // keep
  "a": 1,
  "env": {
    "TOKEN": "x"
  },
  "b": 2
}
"""
    assert (
        remove_settings_keys(text, ["env"])
        == """{
  // keep
  "a": 1,
  "b": 2
}
"""
    )


def test_remove_last_key_drops_the_preceding_comma() -> None:
    text = '{\n  "a": 1,\n  "b": 2\n}\n'
    assert remove_settings_keys(text, ["b"]) == '{\n  "a": 1\n}\n'


def test_remove_last_key_with_trailing_comma_keeps_style() -> None:
    text = '{\n  "a": 1,\n  "b": 2,\n}\n'
    assert remove_settings_keys(text, ["b"]) == '{\n  "a": 1,\n}\n'


def test_remove_only_key_and_crlf() -> None:
    assert remove_settings_keys('{\r\n  "a": 1\r\n}\r\n', ["a"]) == "{\r\n}\r\n"


def test_remove_inline_key_keeps_valid_jsonc() -> None:
    text = '{ "a": 1, "b": 2, "c": 3 } // tail\n'
    result = remove_settings_keys(text, ["b", "c"])
    assert loads(result) == {"a": 1}
    assert result.endswith("// tail\n")


def test_remove_keeps_a_trailing_comment_on_the_line() -> None:
    text = '{\n  "a": 1,\n  "b": 2, // note\n  "c": 3\n}\n'
    result = remove_settings_keys(text, ["b"])
    assert loads(result) == {"a": 1, "c": 3}
    assert "// note" in result


def _sample(root: Path, code_dir) -> None:
    code_dir(
        root,
        [
            {"location": "py", "name": "Python"},
            {"location": "az", "name": "azure"},
            {"location": "java", "name": "java", "useDefaultFlags": {"settings": True}},
        ],
        {
            None: '{\n  "a": 1\n}\n',
            "py": '{\n  "a": 1,\n  "claudeCode.x": true\n}\n',
            "az": '{\n  "a": 1,\n  "claudeCode.environmentVariables": [{"name": "T", '
            '"value": "SECRET"}],\n  "claudeCode.x": true\n}\n',
            "java": "{}\n",
        },
    )


def test_remove_dry_run_reports_without_writing(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    before = _settings(root, "az").read_bytes()
    code = main(
        [
            "--user-data-dir",
            str(root),
            "remove",
            "--profile",
            "all",
            "--prefix",
            "claudeCode.",
            "--exclude-key",
            "claudeCode.x",
            "--mask",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines() == [
        "skip\tjava",
        "Default\tclaudeCode.environmentVariables\tabsent",
        "Python\tclaudeCode.environmentVariables\tabsent",
        'azure\tclaudeCode.environmentVariables\tremove\t[{"name": "***", "value": "***"}]',
    ]
    assert "SECRET" not in out
    assert _settings(root, "az").read_bytes() == before


def test_remove_write_backs_up_and_edits(
    tmp_path: Path,
    code_dir,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("LOCALAPPDATA", str(cache))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setattr("vscode_profiles.apply.code_process_running", lambda: False)
    root = tmp_path / "Code"
    _sample(root, code_dir)
    original = _settings(root, "az").read_text(encoding="utf-8")
    code = main(
        [
            "--user-data-dir",
            str(root),
            "remove",
            "--profile",
            "azure",
            "--key",
            "claudeCode.environmentVariables",
            "--write",
        ]
    )
    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[1].startswith("backup\tazure\t")
    assert _settings(root, "az").read_text(encoding="utf-8") == (
        '{\n  "a": 1,\n  "claudeCode.x": true\n}\n'
    )
    backup = Path(out[1].split("\t", 2)[2])
    assert backup.read_text(encoding="utf-8") == original


def test_remove_absent_key_everywhere_is_a_no_op(
    tmp_path: Path,
    code_dir,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("vscode_profiles.apply.code_process_running", lambda: True)
    root = tmp_path / "Code"
    _sample(root, code_dir)
    args = ["--user-data-dir", str(root), "remove", "--profile", "Default", "--key", "zzz"]
    assert main([*args, "--write"]) == 0
    assert capsys.readouterr().out.splitlines() == ["Default\tzzz\tabsent"]


def test_remove_refuses_while_code_is_running(
    tmp_path: Path,
    code_dir,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("vscode_profiles.apply.code_process_running", lambda: True)
    root = tmp_path / "Code"
    _sample(root, code_dir)
    args = ["--user-data-dir", str(root), "remove", "--profile", "Python", "--key", "claudeCode.x"]
    assert main([*args, "--write"]) == 1
    assert "Code" in capsys.readouterr().err


def test_remove_usage_errors(tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    base = ["--user-data-dir", str(root), "remove"]
    assert main([*base, "--profile", "Default"]) == 2
    assert main([*base, "--profile", "java", "--key", "a"]) == 1
    assert main([*base, "--profile", "Default", "--prefix", "nomatch."]) == 1
    assert capsys.readouterr().err != ""
