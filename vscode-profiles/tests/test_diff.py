from __future__ import annotations

from vscode_profiles.cli import main


def _sample(root, code_dir) -> None:
    code_dir(
        root,
        [
            {"location": "py", "name": "Python"},
            {"location": "node", "name": "Node"},
            {"location": "java", "name": "java", "useDefaultFlags": {"settings": True}},
        ],
        {
            None: """
            {
              "a": 1,
              "b": 1,
              "c": 1,
              "claudeCode.selectedModel": "SECRET_A",
              "claudeCodeExtra": "SECRET_EXTRA",
              "d": {"x": 1, "y": 2},
              "f": 1
            }
            """,
            "py": """
            {
              "a": 1,
              "b": 2,
              "claudeCode.selectedModel": "SECRET_B",
              "d": {"y": 2, "x": 1},
              "e": 1
            }
            """,
            "node": """
            {
              "a": 1,
              "b": 2,
              "c": 1,
              "claudeCode.selectedModel": "SECRET_B",
              "claudeCodeExtra": "SECRET_EXTRA",
              "d": {"x": 1, "y": 2},
              "e": 2
            }
            """,
            "java": '{"only.java": "SECRET_JAVA",}',
        },
    )


def test_diff_prints_key_and_status_without_values(tmp_path, code_dir, capsys) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    assert main(["--user-data-dir", str(root), "diff"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [
        "a\tsame",
        "b\tdifferent",
        "c\tmissing",
        "claudeCode.selectedModel\tdifferent",
        "claudeCodeExtra\tmissing",
        "d\tsame",
        "e\tdifferent",
        "f\tmissing",
    ]
    assert "SECRET_A" not in captured.out
    assert "SECRET_JAVA" not in captured.out
    assert "only.java" not in captured.out


def test_diff_prefix_shows_values_and_does_not_match_longer_stem(
    tmp_path, code_dir, capsys
) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    assert main(["--user-data-dir", str(root), "diff", "--prefix", "claudeCode."]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [
        "claudeCode.selectedModel\tdifferent\t"
        '{"Default": "SECRET_A", "Node": "SECRET_B", "Python": "SECRET_B"}'
    ]
    assert "SECRET_EXTRA" not in captured.out
    assert "SECRET_JAVA" not in captured.out


def test_diff_key_shows_absent_profiles_as_null(tmp_path, code_dir, capsys) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    assert main(["--user-data-dir", str(root), "diff", "--key", "c"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        'c\tmissing\t{"Default": 1, "Node": 1, "Python": null}'
    ]


def test_diff_key_and_prefix_intersect(tmp_path, code_dir, capsys) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    assert (
        main(
            [
                "--user-data-dir",
                str(root),
                "diff",
                "--key",
                "a",
                "--prefix",
                "claudeCode.",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == ""


def test_diff_unknown_key_prints_nothing(tmp_path, code_dir, capsys) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    assert main(["--user-data-dir", str(root), "diff", "--key", "missing.key"]) == 0
    assert capsys.readouterr().out == ""


def test_diff_rejects_empty_selector(tmp_path, code_dir, capsys) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    assert main(["--user-data-dir", str(root), "diff", "--prefix", ""]) == 2
    assert main(["--user-data-dir", str(root), "diff", "--key", ""]) == 2
    err = capsys.readouterr().err
    assert err != ""


def test_diff_single_profile_marks_keys_same(tmp_path, code_dir, capsys) -> None:
    root = tmp_path / "Code"
    code_dir(root, [], {None: '{"editor.fontSize": 14}'})
    assert main(["--user-data-dir", str(root), "diff", "--key", "editor.fontSize"]) == 0
    assert capsys.readouterr().out.splitlines() == ['editor.fontSize\tsame\t{"Default": 14}']
