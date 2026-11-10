from __future__ import annotations

import json
from pathlib import Path

import pytest


def write_code_dir(
    root: Path,
    profiles: list[dict[str, object]],
    settings: dict[str | None, str],
) -> None:
    storage = root / "User" / "globalStorage"
    storage.mkdir(parents=True)
    (storage / "storage.json").write_text(
        json.dumps({"userDataProfiles": profiles}),
        encoding="utf-8",
        newline="",
    )
    for location, text in settings.items():
        if location is None:
            path = root / "User" / "settings.json"
        else:
            path = root / "User" / "profiles" / Path(location) / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")


@pytest.fixture
def code_dir():
    return write_code_dir
