from __future__ import annotations

from pathlib import Path

import pytest

from vscode_profiles.cli import main


def _sample(root: Path, code_dir) -> None:
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {
            None: (
                '{ "claudeCode.a": 1, "claudeCode.environmentVariables": [{"name": "T", '
                '"value": "SECRET"}], "claudeCode.b": 2 }\n'
            ),
            "py": '{ "claudeCode.a": 1 }\n',
        },
    )


def test_diff_exclude_key_drops_prefix_matches(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    args = ["--user-data-dir", str(root), "diff", "--prefix", "claudeCode."]
    assert main([*args, "--exclude-key", "claudeCode.environmentVariables"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines() == [
        'claudeCode.a\tsame\t{"Default": 1, "Python": 1}',
        'claudeCode.b\tmissing\t{"Default": 2, "Python": null}',
    ]
    assert "SECRET" not in out


def test_diff_exclude_key_without_selector_filters_status_lines(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    args = ["--user-data-dir", str(root), "diff", "--exclude-key", "claudeCode.b"]
    assert main(args) == 0
    assert capsys.readouterr().out.splitlines() == [
        "claudeCode.a\tsame",
        "claudeCode.environmentVariables\tmissing",
    ]


def test_apply_exclude_key_drops_prefix_matches(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    code = main(
        [
            "--user-data-dir",
            str(root),
            "apply",
            "--from",
            "Default",
            "--to",
            "Python",
            "--prefix",
            "claudeCode.",
            "--exclude-key",
            "claudeCode.environmentVariables",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines() == [
        "Python\tclaudeCode.a\tsame\t1",
        "Python\tclaudeCode.b\tadd\t2",
    ]


def test_apply_everything_excluded_matches_nothing(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    code = main(
        [
            "--user-data-dir",
            str(root),
            "apply",
            "--from",
            "Default",
            "--to",
            "Python",
            "--key",
            "claudeCode.a",
            "--exclude-key",
            "claudeCode.a",
        ]
    )
    assert code == 1
    assert "no keys matched" in capsys.readouterr().err


def test_empty_exclude_key_is_a_usage_error(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    assert main(["--user-data-dir", str(root), "diff", "--exclude-key", ""]) == 2
    assert capsys.readouterr().err != ""
