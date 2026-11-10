from __future__ import annotations

import json
from pathlib import Path

import pytest

from vscode_profiles.apply import (
    _csv_has_image,
    _posix_is_code,
    commit_settings,
    user_cache_dir,
)
from vscode_profiles.cli import main


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _apply(root: Path, *args: str) -> list[str]:
    return ["--user-data-dir", str(root), "apply", *args]


def _settings(root: Path, location: str | None) -> Path:
    if location is None:
        return root / "User" / "settings.json"
    return root / "User" / "profiles" / Path(location) / "settings.json"


def test_apply_dry_run_reports_add_replace_and_same_without_writing(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    default_text = """{
  // keep
  "editor.fontSize": 14,
  "editor.tabSize": 4,
  "obj": {"a": 1, "b": 2},
  "same": true,
}
"""
    python_text = """{
  "editor.fontSize": 16,
  "obj": {"a": 9},
  "same": true,
}
"""
    node_text = """{
  "same": true,
}
"""
    code_dir(
        root,
        [
            {"location": "py", "name": "Python"},
            {"location": "node", "name": "Node"},
        ],
        {None: default_text, "py": python_text, "node": node_text},
    )
    storage = (root / "User" / "globalStorage" / "storage.json").read_bytes()
    code = main(
        _apply(
            root,
            "--from",
            "Default",
            "--to",
            "Python",
            "--to",
            "Node",
            "--key",
            "editor.fontSize",
            "--key",
            "same",
            "--key",
            "editor.tabSize",
            "--key",
            "obj",
        )
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out.splitlines() == [
        f"Node\teditor.fontSize\tadd\t{_dumps(14)}",
        f"Node\teditor.tabSize\tadd\t{_dumps(4)}",
        f"Node\tobj\tadd\t{_dumps({'a': 1, 'b': 2})}",
        f"Node\tsame\tsame\t{_dumps(True)}",
        f"Python\teditor.fontSize\treplace\t{_dumps(14)}\t{_dumps(16)}",
        f"Python\teditor.tabSize\tadd\t{_dumps(4)}",
        f"Python\tobj\treplace\t{_dumps({'a': 1, 'b': 2})}\t{_dumps({'a': 9})}",
        f"Python\tsame\tsame\t{_dumps(True)}",
    ]
    assert _settings(root, None).read_text(encoding="utf-8") == default_text
    assert _settings(root, "py").read_text(encoding="utf-8") == python_text
    assert _settings(root, "node").read_text(encoding="utf-8") == node_text
    assert (root / "User" / "globalStorage" / "storage.json").read_bytes() == storage


def test_apply_missing_source_key_changes_nothing(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    default_text = '{ "editor.fontSize": 14 }\n'
    python_text = '{ "editor.fontSize": 16 }\n'
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: default_text, "py": python_text},
    )
    code = main(
        _apply(
            root,
            "--from",
            "Default",
            "--to",
            "Python",
            "--key",
            "editor.fontSize",
            "--key",
            "missing",
        )
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "missing" in captured.err
    assert captured.out == ""
    assert _settings(root, "py").read_text(encoding="utf-8") == python_text
    assert _settings(root, None).read_text(encoding="utf-8") == default_text


def test_apply_rejects_inherit_source_and_destination(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    default_text = '{ "editor.fontSize": 14 }\n'
    python_text = '{ "editor.fontSize": 16 }\n'
    java_text = "SECRET_JAVA_NOT_READ"
    code_dir(
        root,
        [
            {"location": "py", "name": "Python"},
            {"location": "java", "name": "java", "useDefaultFlags": {"settings": True}},
        ],
        {None: default_text, "py": python_text, "java": java_text},
    )
    from_inherit = main(
        _apply(root, "--from", "java", "--to", "Python", "--key", "editor.fontSize")
    )
    from_err = capsys.readouterr()
    assert from_inherit == 1
    assert "inherit" in from_err.err
    assert "SECRET_JAVA" not in from_err.out
    assert _settings(root, "py").read_text(encoding="utf-8") == python_text

    to_inherit = main(
        _apply(
            root,
            "--from",
            "Default",
            "--to",
            "Python",
            "--to",
            "java",
            "--key",
            "editor.fontSize",
        )
    )
    to_err = capsys.readouterr()
    assert to_inherit == 1
    assert "inherit" in to_err.err
    assert _settings(root, "py").read_text(encoding="utf-8") == python_text
    assert _settings(root, "java").read_text(encoding="utf-8") == java_text


def test_apply_all_skips_inherit_and_excludes_source(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    code_dir(
        root,
        [
            {"location": "py", "name": "Python"},
            {"location": "java", "name": "java", "useDefaultFlags": {"settings": True}},
            {
                "location": "builtin/agents",
                "name": "Agents",
                "useDefaultFlags": {"settings": True},
            },
        ],
        {
            None: '{ "editor.fontSize": 14 }\n',
            "py": '{ "editor.fontSize": 16 }\n',
            "java": "SECRET_JAVA",
            "builtin/agents": "SECRET_AGENTS",
        },
    )
    code = main(_apply(root, "--from", "Default", "--to", "all", "--key", "editor.fontSize"))
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out.splitlines() == [
        "skip\tAgents",
        "skip\tjava",
        f"Python\teditor.fontSize\treplace\t{_dumps(14)}\t{_dumps(16)}",
    ]
    assert "SECRET" not in captured.out
    assert "Default\t" not in captured.out


def test_apply_prefix_uses_source_keys_only(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {
            None: '{ "claudeCode.selectedModel": "A", "claudeCodeExtra": "no" }\n',
            "py": '{ "claudeCode.onlyDest": "B" }\n',
        },
    )
    code = main(_apply(root, "--from", "Default", "--to", "Python", "--prefix", "claudeCode."))
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.splitlines() == [
        'Python\tclaudeCode.selectedModel\tadd\t"A"',
    ]
    assert "claudeCodeExtra" not in captured.out
    assert "onlyDest" not in captured.out


def test_apply_prefix_with_no_match_writes_nothing(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    python_text = '{ "editor.fontSize": 16 }\n'
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: '{ "editor.fontSize": 14 }\n', "py": python_text},
    )
    code = main(_apply(root, "--from", "Default", "--to", "Python", "--prefix", "nope."))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err != ""
    assert _settings(root, "py").read_text(encoding="utf-8") == python_text


def test_apply_key_and_prefix_intersect(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {
            None: '{ "editor.fontSize": 14, "editor.tabSize": 4, "other": 1 }\n',
            "py": "{}\n",
        },
    )
    code = main(
        _apply(
            root,
            "--from",
            "Default",
            "--to",
            "Python",
            "--key",
            "editor.fontSize",
            "--key",
            "other",
            "--prefix",
            "editor.",
        )
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.splitlines() == [
        f"Python\teditor.fontSize\tadd\t{_dumps(14)}",
    ]


def test_apply_usage_errors(tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "Code"
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: "{}\n", "py": "{}\n"},
    )
    with pytest.raises(SystemExit) as missing_from:
        main(_apply(root, "--to", "Python", "--key", "a"))
    assert missing_from.value.code == 2

    with pytest.raises(SystemExit) as missing_to:
        main(_apply(root, "--from", "Default", "--key", "a"))
    assert missing_to.value.code == 2

    assert main(_apply(root, "--from", "Default", "--to", "Python")) == 2
    assert main(_apply(root, "--from", "Default", "--to", "Python", "--key", "")) == 2
    assert main(_apply(root, "--from", "Default", "--to", "Python", "--prefix", "")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""


def test_apply_unknown_profile_changes_nothing(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    python_text = '{ "a": 1 }\n'
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: '{ "a": 2 }\n', "py": python_text},
    )
    code = main(_apply(root, "--from", "Missing", "--to", "Python", "--key", "a"))
    captured = capsys.readouterr()
    assert code == 1
    assert "Missing" in captured.err
    assert _settings(root, "py").read_text(encoding="utf-8") == python_text


def test_apply_unlocatable_key_blocks_every_destination(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    python_text = '{\n  "a": 1,\n  "a": 2,\n}\n'
    node_text = '{\n  "a": 0,\n}\n'
    code_dir(
        root,
        [
            {"location": "py", "name": "Python"},
            {"location": "node", "name": "Node"},
        ],
        {None: '{ "a": 3 }\n', "py": python_text, "node": node_text},
    )
    code = main(_apply(root, "--from", "Default", "--to", "Python", "--to", "Node", "--key", "a"))
    captured = capsys.readouterr()
    assert code == 1
    assert "cannot edit" in captured.err
    assert captured.out == ""
    assert _settings(root, "py").read_text(encoding="utf-8") == python_text
    assert _settings(root, "node").read_text(encoding="utf-8") == node_text


def test_write_preserves_jsonc_and_backs_up_outside_the_profile(
    tmp_path: Path,
    code_dir,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("LOCALAPPDATA", str(cache))
    root = tmp_path / "Code"
    default_text = """{
  // keep
  "added": "x",
  "editor.fontSize": 14,
  "items": [1, 2,],
  "obj": {"a": 1},
  "zebra": "z",
}
"""
    python_text = """{
  "editor.fontSize": 16, // mine
  "obj": {
    // dest only
    "a": 9,
    "c": 3
  },
  "other": "stay"
}
"""
    code_dir(
        root,
        [{"location": "team/ai", "name": "ai"}],
        {None: default_text, "team/ai": python_text},
    )
    code = main(
        _apply(
            root,
            "--from",
            "Default",
            "--to",
            "ai",
            "--key",
            "added",
            "--key",
            "editor.fontSize",
            "--key",
            "items",
            "--key",
            "obj",
            "--key",
            "zebra",
            "--write",
            "--force",
        )
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    expected = """{
  "editor.fontSize": 14, // mine
  "obj": {"a": 1},
  "other": "stay",
  "added": "x",
  "items": [1, 2],
  "zebra": "z"
}
"""
    written = _settings(root, "team/ai").read_text(encoding="utf-8")
    assert written == expected
    assert _settings(root, None).read_text(encoding="utf-8") == default_text
    backup_lines = [line for line in captured.out.splitlines() if line.startswith("backup\t")]
    assert len(backup_lines) == 1
    backup = Path(backup_lines[0].split("\t", 2)[2])
    assert cache in backup.parents
    assert root not in backup.parents
    assert backup.read_text(encoding="utf-8") == python_text
    assert not list(root.rglob("*.vscode-profiles-tmp"))


def test_write_keeps_same_values_and_crlf(
    tmp_path: Path,
    code_dir,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "cache"))
    root = tmp_path / "Code"
    python_text = '{\r\n  "obj": {\r\n    "a": 1\r\n  },\r\n  "n": 1\r\n}\r\n'
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: '{ "obj": {"a": 1}, "n": 2 }\n', "py": python_text},
    )
    code = main(
        _apply(
            root,
            "--from",
            "Default",
            "--to",
            "Python",
            "--key",
            "obj",
            "--key",
            "n",
            "--write",
            "--force",
        )
    )
    captured = capsys.readouterr()
    assert code == 0
    assert f"Python\tobj\tsame\t{_dumps({'a': 1})}" in captured.out.splitlines()
    assert _settings(root, "py").read_bytes() == (
        b'{\r\n  "obj": {\r\n    "a": 1\r\n  },\r\n  "n": 2\r\n}\r\n'
    )
    assert "backup\t" in captured.out


def test_write_of_identical_keys_does_not_back_up(
    tmp_path: Path,
    code_dir,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("LOCALAPPDATA", str(cache))
    root = tmp_path / "Code"
    python_text = '{ "n": 1 }\n'
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: '{ "n": 1 }\n', "py": python_text},
    )
    code = main(
        _apply(root, "--from", "Default", "--to", "Python", "--key", "n", "--write", "--force")
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "backup\t" not in captured.out
    assert _settings(root, "py").read_text(encoding="utf-8") == python_text
    assert not cache.exists()


def test_write_adds_with_detected_indent_and_keeps_trailing_comment(
    tmp_path: Path,
    code_dir,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "cache"))
    root = tmp_path / "Code"
    python_text = '{\n    "a": 1\n    // end\n}\n'
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: '{ "a": 1, "b": 2 }\n', "py": python_text},
    )
    code = main(
        _apply(root, "--from", "Default", "--to", "Python", "--key", "b", "--write", "--force")
    )
    assert code == 0
    capsys.readouterr()
    assert (
        _settings(root, "py").read_text(encoding="utf-8")
        == '{\n    "a": 1,\n    // end\n    "b": 2\n}\n'
    )


def test_write_refuses_while_code_is_running_unless_forced(
    tmp_path: Path,
    code_dir,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("LOCALAPPDATA", str(cache))
    monkeypatch.setattr("vscode_profiles.apply.code_process_running", lambda: True)
    root = tmp_path / "Code"
    python_text = '{ "n": 1 }\n'
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: '{ "n": 2 }\n', "py": python_text},
    )
    refused = main(_apply(root, "--from", "Default", "--to", "Python", "--key", "n", "--write"))
    refused_out = capsys.readouterr()
    assert refused == 1
    assert refused_out.out == ""
    assert "Code" in refused_out.err
    assert _settings(root, "py").read_text(encoding="utf-8") == python_text
    assert not cache.exists()

    forced = main(
        _apply(root, "--from", "Default", "--to", "Python", "--key", "n", "--write", "--force")
    )
    forced_out = capsys.readouterr()
    assert forced == 0
    assert forced_out.err == ""
    assert _settings(root, "py").read_text(encoding="utf-8") == '{ "n": 2 }\n'


def test_dry_run_does_not_check_the_code_process(
    tmp_path: Path,
    code_dir,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called() -> bool:
        raise AssertionError("process check")

    monkeypatch.setattr("vscode_profiles.apply.code_process_running", fail_if_called)
    root = tmp_path / "Code"
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: '{ "n": 2 }\n', "py": '{ "n": 1 }\n'},
    )
    assert main(_apply(root, "--from", "Default", "--to", "Python", "--key", "n")) == 0


def test_write_restores_failed_destination_and_leaves_the_rest(
    tmp_path: Path,
    code_dir,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "cache"))
    root = tmp_path / "Code"
    texts = {
        "a": '{ "n": 1 }\n',
        "b": '{ "n": 1 }\n',
        "c": '{ "n": 1 }\n',
    }
    code_dir(
        root,
        [
            {"location": "a", "name": "A"},
            {"location": "b", "name": "B"},
            {"location": "c", "name": "C"},
        ],
        {None: '{ "n": 2 }\n', **texts},
    )
    calls = {"n": 0}

    def flaky(tmp: Path, dest: Path) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            dest.write_text("DAMAGED", encoding="utf-8")
            raise OSError("disk full")
        commit_settings(tmp, dest)

    monkeypatch.setattr("vscode_profiles.apply.commit_settings", flaky)
    code = main(
        _apply(root, "--from", "Default", "--to", "all", "--key", "n", "--write", "--force")
    )
    captured = capsys.readouterr()
    assert code == 1
    assert _settings(root, "a").read_text(encoding="utf-8") == '{ "n": 2 }\n'
    assert _settings(root, "b").read_text(encoding="utf-8") == texts["b"]
    assert _settings(root, "c").read_text(encoding="utf-8") == texts["c"]
    assert "restore\tB\tok" in captured.out.splitlines()
    assert "disk full" in captured.err


def test_restore_reports_failure_when_backup_cannot_be_read(
    tmp_path: Path,
    code_dir,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "cache"))
    root = tmp_path / "Code"
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: '{ "n": 2 }\n', "py": '{ "n": 1 }\n'},
    )

    def break_dest(tmp: Path, dest: Path) -> None:
        dest.write_text("DAMAGED", encoding="utf-8")
        backup = tmp_path / "cache"
        for path in backup.rglob("settings.json"):
            path.unlink()
        raise OSError("disk full")

    monkeypatch.setattr("vscode_profiles.apply.commit_settings", break_dest)
    code = main(
        _apply(root, "--from", "Default", "--to", "Python", "--key", "n", "--write", "--force")
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "restore\tPython\tfailed" in captured.out.splitlines()
    assert _settings(root, "py").read_text(encoding="utf-8") == "DAMAGED"


def test_user_cache_dir_follows_the_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vscode_profiles.apply.platform.system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
    assert user_cache_dir() == Path(r"C:\Users\me\AppData\Local") / "vscode-profiles"

    monkeypatch.setattr("vscode_profiles.apply.platform.system", lambda: "Darwin")
    monkeypatch.setattr("vscode_profiles.apply.Path.home", lambda: Path("/Users/me"))
    assert user_cache_dir() == Path("/Users/me/Library/Caches/vscode-profiles")

    monkeypatch.setattr("vscode_profiles.apply.platform.system", lambda: "Linux")
    monkeypatch.setenv("XDG_CACHE_HOME", "/home/me/.cache")
    assert user_cache_dir() == Path("/home/me/.cache/vscode-profiles")
    monkeypatch.delenv("XDG_CACHE_HOME")
    monkeypatch.setattr("vscode_profiles.apply.Path.home", lambda: Path("/home/me"))
    assert user_cache_dir() == Path("/home/me/.cache/vscode-profiles")


def test_process_name_matching() -> None:
    assert _csv_has_image('"Code.exe","1234","Console","1","1 K"\n', "Code.exe")
    assert not _csv_has_image(
        "INFO: No tasks are running which match the specified criteria.", "Code.exe"
    )
    assert not _csv_has_image('"Code - Insiders.exe","1","Console","1","1 K"\n', "Code.exe")
    assert _posix_is_code("Code")
    assert _posix_is_code("code")
    assert _posix_is_code("/usr/share/code/code")
    assert not _posix_is_code("code-insiders")
    assert not _posix_is_code("Cursor")


def test_apply_rejects_source_key_before_prefix_filter(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    python_text = '{ "editor.fontSize": 16 }\n'
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: '{ "editor.fontSize": 14 }\n', "py": python_text},
    )
    code = main(
        _apply(
            root,
            "--from",
            "Default",
            "--to",
            "Python",
            "--key",
            "missing",
            "--prefix",
            "editor.",
        )
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "missing" in captured.err
    assert _settings(root, "py").read_text(encoding="utf-8") == python_text


def test_commit_settings_replaces_destination(tmp_path: Path) -> None:
    dest = tmp_path / "settings.json"
    dest.write_text("old", encoding="utf-8")
    tmp = tmp_path / "settings.json.vscode-profiles-tmp"
    tmp.write_text("new", encoding="utf-8")
    commit_settings(tmp, dest)
    assert dest.read_text(encoding="utf-8") == "new"
    assert not tmp.exists()


def test_windows_cache_without_localappdata_uses_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vscode_profiles.apply.platform.system", lambda: "Windows")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr("vscode_profiles.apply.Path.home", lambda: Path("/Users/me"))
    assert user_cache_dir() == Path("/Users/me/AppData/Local/vscode-profiles")


def test_code_process_running_uses_tasklist_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    from vscode_profiles.apply import code_process_running

    monkeypatch.setattr("vscode_profiles.apply.platform.system", lambda: "Windows")

    class Result:
        stdout = '"Code.exe","10","Console","1","1 K"\n'

    monkeypatch.setattr("vscode_profiles.apply.subprocess.run", lambda *args, **kwargs: Result())
    assert code_process_running() is True


def test_code_process_running_uses_ps_on_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    from vscode_profiles.apply import code_process_running

    monkeypatch.setattr("vscode_profiles.apply.platform.system", lambda: "Linux")

    class Result:
        stdout = "bash\ncode\n"

    monkeypatch.setattr("vscode_profiles.apply.subprocess.run", lambda *args, **kwargs: Result())
    assert code_process_running() is True


def test_apply_same_object_with_different_key_order_is_same(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    python_text = '{ "obj": {"b": 2, "a": 1} }\n'
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: '{ "obj": {"a": 1, "b": 2} }\n', "py": python_text},
    )
    code = main(_apply(root, "--from", "Default", "--to", "Python", "--key", "obj"))
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.splitlines() == [f"Python\tobj\tsame\t{_dumps({'a': 1, 'b': 2})}"]
    assert _settings(root, "py").read_text(encoding="utf-8") == python_text


def test_apply_true_and_one_are_not_the_same(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: '{ "flag": true }\n', "py": '{ "flag": 1 }\n'},
    )
    code = main(_apply(root, "--from", "Default", "--to", "Python", "--key", "flag"))
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.splitlines() == ["Python\tflag\treplace\ttrue\t1"]
