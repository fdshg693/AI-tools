from __future__ import annotations

from collections.abc import Iterable, Sequence

from vscode_profiles.errors import CliError


def check_selectors(keys: Sequence[str], prefix: str | None, exclude: Sequence[str]) -> None:
    if prefix == "":
        raise CliError("prefix must not be empty", code=2)
    if any(key == "" for key in keys):
        raise CliError("key must not be empty", code=2)
    if any(key == "" for key in exclude):
        raise CliError("exclude-key must not be empty", code=2)


def select_keys(
    candidates: Iterable[str],
    keys: Sequence[str],
    prefix: str | None,
    exclude: Sequence[str],
) -> list[str]:
    wanted = set(keys)
    dropped = set(exclude)
    found: list[str] = []
    for key in sorted(candidates):
        if wanted and key not in wanted:
            continue
        if prefix is not None and not key.startswith(prefix):
            continue
        if key in dropped:
            continue
        found.append(key)
    return found
