from __future__ import annotations

from pathlib import Path

import pytest

from vscode_profiles.cli import main


def _sample(root: Path, code_dir) -> None:
    code_dir(
        root,
        [
            {"location": "py", "name": "Python"},
            {"location": "node", "name": "Node"},
            {"location": "java", "name": "java", "useDefaultFlags": {"settings": True}},
        ],
        {
            None: '{ "model": "SECRET_A", "flag": true, "obj": {"x": 1, "y": 2} }\n',
            "py": '{ "model": "SECRET_B", "flag": 1, "obj": {"y": 2, "x": 1} }\n',
            "node": '{ "model": "SECRET_A" }\n',
            "java": '{ "model": "SECRET_JAVA" }\n',
        },
    )


def test_by_profile_prints_value_groups_without_values(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    assert main(["--user-data-dir", str(root), "diff", "--by-profile"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines() == [
        'flag\tdifferent\t{"Default": 1, "Node": null, "Python": 2}',
        'model\tdifferent\t{"Default": 1, "Node": 1, "Python": 2}',
        'obj\tmissing\t{"Default": 1, "Node": null, "Python": 1}',
    ]
    assert "SECRET" not in out


def test_by_profile_wins_over_value_output(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    args = ["--user-data-dir", str(root), "diff", "--key", "model", "--by-profile"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert out.splitlines() == ['model\tdifferent\t{"Default": 1, "Node": 1, "Python": 2}']
    assert "SECRET" not in out
