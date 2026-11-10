from __future__ import annotations

from pathlib import Path

import pytest

from vscode_profiles.errors import CliError
from vscode_profiles.paths import default_user_data_dir


def test_windows_default_is_appdata_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vscode_profiles.paths.platform.system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", r"C:\Users\me\AppData\Roaming")
    assert default_user_data_dir() == Path(r"C:\Users\me\AppData\Roaming") / "Code"


def test_windows_without_appdata_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vscode_profiles.paths.platform.system", lambda: "Windows")
    monkeypatch.delenv("APPDATA", raising=False)
    with pytest.raises(CliError, match="APPDATA"):
        default_user_data_dir()


def test_darwin_default_is_application_support(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vscode_profiles.paths.platform.system", lambda: "Darwin")
    monkeypatch.setattr("vscode_profiles.paths.Path.home", lambda: Path("/Users/me"))
    assert default_user_data_dir() == Path("/Users/me/Library/Application Support/Code")


def test_linux_default_is_config_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vscode_profiles.paths.platform.system", lambda: "Linux")
    monkeypatch.setattr("vscode_profiles.paths.Path.home", lambda: Path("/home/me"))
    assert default_user_data_dir() == Path("/home/me/.config/Code")
