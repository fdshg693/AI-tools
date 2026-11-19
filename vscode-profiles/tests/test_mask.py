from __future__ import annotations

from pathlib import Path

import pytest

from vscode_profiles.cli import main
from vscode_profiles.diff import mask_value


def _sample(root: Path, code_dir) -> None:
    code_dir(
        root,
        [{"location": "py", "name": "Python"}],
        {
            None: (
                '{ "env": [{"name": "TOKEN", "value": "SECRET_A"}], '
                '"obj": {"OTEL_HEADERS": "SECRET_B", "n": 3, "on": true} }\n'
            ),
            "py": '{ "obj": {"OTEL_HEADERS": "SECRET_C"} }\n',
        },
    )


def test_mask_value_keeps_shape_and_hides_strings() -> None:
    assert mask_value({"a": "x", "b": [1, "y", None, False]}) == {
        "a": "***",
        "b": [1, "***", None, False],
    }
    assert mask_value("plain") == "***"
    assert mask_value(14) == 14


def test_diff_mask_hides_strings_but_status_uses_real_values(
    tmp_path: Path, code_dir, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Code"
    _sample(root, code_dir)
    assert main(["--user-data-dir", str(root), "diff", "--key", "obj", "--mask"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines() == [
        'obj\tdifferent\t{"Default": {"OTEL_HEADERS": "***", "n": 3, "on": true}, '
        '"Python": {"OTEL_HEADERS": "***"}}'
    ]
    assert "SECRET" not in out


def test_apply_mask_hides_source_and_destination_values(
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
            "env",
            "--key",
            "obj",
            "--mask",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines() == [
        'Python\tenv\tadd\t[{"name": "***", "value": "***"}]',
        'Python\tobj\treplace\t{"OTEL_HEADERS": "***", "n": 3, "on": true}\t'
        '{"OTEL_HEADERS": "***"}',
    ]
    assert "SECRET" not in out
