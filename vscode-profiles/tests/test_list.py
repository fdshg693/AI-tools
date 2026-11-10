from __future__ import annotations

import pytest

from vscode_profiles.cli import main


def test_list_reports_name_inheritance_and_key_count(
    tmp_path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    code_dir(
        root,
        [
            {"location": "node", "name": "Node"},
            {"location": "csharp", "name": "C#"},
            {"location": "py", "name": "Python", "useDefaultFlags": {}},
            {"location": "java", "name": "java", "useDefaultFlags": {"settings": True}},
            {
                "location": "builtin/agents",
                "name": "Agents",
                "useDefaultFlags": {"settings": True, "keybindings": True},
            },
        ],
        {
            None: '{ // kept\n "editor.fontSize": 14, "editor.tabSize": 4, }\n',
            "node": '{"editor.fontSize": 16}',
            "csharp": '{"dotnet.defaultSolution": "app.sln"}',
            "py": '{"python.defaultInterpreterPath": "SECRET_INTERPRETER", "a": {"b": 1}}',
            "java": "this is not read",
            "builtin/agents": "this is not read either",
        },
    )
    assert main(["--user-data-dir", str(root), "list"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [
        "Default\town\t2",
        "Agents\tinherit\t0",
        "C#\town\t1",
        "Node\town\t1",
        "Python\town\t2",
        "java\tinherit\t0",
    ]
    assert "SECRET_INTERPRETER" not in captured.out
    assert "14" not in captured.out


def test_list_without_named_profiles_shows_default(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    storage = root / "User" / "globalStorage"
    storage.mkdir(parents=True)
    (storage / "storage.json").write_text("{}", encoding="utf-8")
    (root / "User" / "settings.json").write_text("{}\n", encoding="utf-8")
    assert main(["--user-data-dir", str(root), "list"]) == 0
    assert capsys.readouterr().out.splitlines() == ["Default\town\t0"]


def test_list_fails_when_own_settings_file_is_missing(
    tmp_path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {None: "{}"},
    )
    assert main(["--user-data-dir", str(root), "list"]) == 1
    err = capsys.readouterr().err
    assert "Python" in err
    assert "settings.json" in err


def test_list_fails_on_duplicate_names_and_prints_locations(
    tmp_path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    code_dir(
        root,
        [
            {"location": "b", "name": "Python"},
            {"location": "a", "name": "Python"},
        ],
        {None: "{}"},
    )
    assert main(["--user-data-dir", str(root), "list"]) == 1
    err = capsys.readouterr().err
    assert "Python" in err
    assert "a" in err
    assert "b" in err


def test_list_rejects_profile_location_outside_profiles_dir(
    tmp_path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    outside = tmp_path / "outside.json"
    outside.write_text('{"leaked": true}', encoding="utf-8")
    code_dir(
        root,
        [{"location": "../outside", "name": "Escape"}],
        {None: "{}"},
    )
    assert main(["--user-data-dir", str(root), "list"]) == 1
    err = capsys.readouterr().err
    assert "Escape" in err or ".." in err
    assert "leaked" not in err


def test_list_fails_when_settings_root_is_not_an_object(
    tmp_path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    code_dir(root, [], {None: "[1, 2]"})
    assert main(["--user-data-dir", str(root), "list"]) == 1
    assert "settings.json" in capsys.readouterr().err


def test_settings_false_flag_is_own(tmp_path, code_dir, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "Code"
    code_dir(
        root,
        [
            {
                "location": "py",
                "name": "Python",
                "useDefaultFlags": {"settings": False, "snippets": True},
            }
        ],
        {None: "{}", "py": '{"editor.fontSize": 14}'},
    )
    assert main(["--user-data-dir", str(root), "list"]) == 0
    assert "Python\town\t1" in capsys.readouterr().out.splitlines()
