from __future__ import annotations

from pathlib import Path

from pyinspect_cli import main
from pyinspect_core.config import EXIT_METADATA_ONLY, EXIT_NOT_FOUND, EXIT_SUCCESS, EXIT_USAGE
from pyinspect_core.inspect import InspectOutcome
from pyinspect_core.pypi import NotFoundError, UsageError


def test_module_without_import_exits_2(capsys) -> None:
    code = main(["demo", "--module", "demo"])
    assert code == EXIT_USAGE
    err = capsys.readouterr().err
    assert "--module" in err


def test_help_exits_zero(capsys) -> None:
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("argparse --help should SystemExit")
    assert "index.md" in capsys.readouterr().out


def test_main_prints_posix_path_only(monkeypatch, capsys, tmp_path: Path) -> None:
    index = tmp_path / "demo" / "1.0.0" / "index.md"
    index.parent.mkdir(parents=True)
    index.write_text("# demo\n", encoding="utf-8")

    def fake_run(specifier, **kwargs):
        assert specifier == "demo"
        return InspectOutcome(EXIT_SUCCESS, index)

    monkeypatch.setattr("pyinspect_cli.run_inspect", fake_run)
    code = main(["demo"])
    assert code == EXIT_SUCCESS
    out = capsys.readouterr().out.strip()
    assert out == index.as_posix()
    assert "\n" not in out


def test_main_not_found_prints_nothing_to_stdout(monkeypatch, capsys) -> None:
    def fake_run(*_args, **_kwargs):
        raise NotFoundError("package or version not found on PyPI: missing")

    monkeypatch.setattr("pyinspect_cli.run_inspect", fake_run)
    code = main(["missing"])
    assert code == EXIT_NOT_FOUND
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not found" in captured.err


def test_main_metadata_only_still_prints_path(monkeypatch, capsys, tmp_path: Path) -> None:
    index = tmp_path / "index.md"
    index.write_text("# x\n", encoding="utf-8")

    def fake_run(*_args, **_kwargs):
        return InspectOutcome(EXIT_METADATA_ONLY, index)

    monkeypatch.setattr("pyinspect_cli.run_inspect", fake_run)
    code = main(["demo"])
    assert code == EXIT_METADATA_ONLY
    assert capsys.readouterr().out.strip() == index.as_posix()


def test_main_usage_from_core(monkeypatch, capsys) -> None:
    def fake_run(*_args, **_kwargs):
        raise UsageError("extras are not supported")

    monkeypatch.setattr("pyinspect_cli.run_inspect", fake_run)
    code = main(["demo[x]"])
    assert code == EXIT_USAGE
    assert "extras" in capsys.readouterr().err
