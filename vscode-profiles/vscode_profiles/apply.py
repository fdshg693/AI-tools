from __future__ import annotations

import csv
import json
import os
import platform
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vscode_profiles.errors import CliError
from vscode_profiles.paths import resolve_user_data_dir
from vscode_profiles.profiles import Profile, load_profiles, read_own_settings


def user_cache_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        if local == "":
            return Path.home() / "AppData" / "Local" / "vscode-profiles"
        return Path(local) / "vscode-profiles"
    if system == "Darwin":
        return Path.home() / "Library" / "Caches" / "vscode-profiles"
    cache_home = os.environ.get("XDG_CACHE_HOME", "")
    if cache_home:
        return Path(cache_home) / "vscode-profiles"
    return Path.home() / ".cache" / "vscode-profiles"


def commit_settings(tmp: Path, dest: Path) -> None:
    os.replace(tmp, dest)


def code_process_running() -> bool:
    system = platform.system()
    if system == "Windows":
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Code.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return _csv_has_image(completed.stdout, "Code.exe")
    completed = subprocess.run(
        ["ps", "-A", "-o", "comm="],
        capture_output=True,
        text=True,
        check=False,
    )
    return any(_posix_is_code(line.strip()) for line in completed.stdout.splitlines())


def _csv_has_image(stdout: str, image: str) -> bool:
    for line in stdout.splitlines():
        if line == "":
            continue
        try:
            fields = next(csv.reader([line]))
        except csv.Error:
            continue
        if fields and fields[0] == image:
            return True
    return False


def _posix_is_code(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    return base in {"Code", "code"}


def run_apply(
    user_data_dir: Path | None,
    *,
    source: str,
    destinations: Sequence[str],
    keys: Sequence[str],
    prefix: str | None,
    write: bool,
    force: bool,
) -> int:
    if prefix == "":
        raise CliError("prefix must not be empty", code=2)
    if any(key == "" for key in keys):
        raise CliError("key must not be empty", code=2)
    if not keys and prefix is None:
        raise CliError("apply requires --key or --prefix", code=2)

    profiles = load_profiles(resolve_user_data_dir(user_data_dir))
    by_name = {profile.name: profile for profile in profiles}
    source_profile = by_name.get(source)
    if source_profile is None:
        raise CliError(f"profile {source!r} was not found")
    if source_profile.inherits_settings:
        raise CliError(f"profile {source!r} inherits settings and cannot be a source")

    chosen, skips = _destinations(profiles, source_profile.name, destinations)
    source_values = read_own_settings(source_profile)
    for key in keys:
        if key not in source_values:
            raise CliError(f"key {key!r} is not in source profile {source_profile.name!r}")
    selected = _selected_keys(source_values, keys, prefix)
    if not selected:
        raise CliError("no keys matched")

    planned: list[_Planned] = []
    for profile in chosen:
        planned.append(_plan_destination(profile, selected, source_values))

    pending = [item for item in planned if item.new_text != item.original]
    if write and pending and not force and code_process_running():
        raise CliError("VS Code stable (Code) is running; pass --force to write")

    for profile in skips:
        print(f"skip\t{profile.name}")
    for item in planned:
        for line in item.lines:
            print(line)
    if write and pending:
        _write_all(pending)
    return 0


@dataclass(frozen=True)
class _Planned:
    profile: Profile
    original: str
    new_text: str
    lines: tuple[str, ...]


def _destinations(
    profiles: Sequence[Profile],
    source_name: str,
    names: Sequence[str],
) -> tuple[list[Profile], list[Profile]]:
    by_name = {profile.name: profile for profile in profiles}
    chosen: list[Profile] = []
    seen: set[str] = set()
    for name in names:
        if name == "all":
            continue
        profile = by_name.get(name)
        if profile is None:
            raise CliError(f"profile {name!r} was not found")
        if profile.inherits_settings:
            raise CliError(f"profile {name!r} inherits settings and cannot be a destination")
        if name not in seen:
            chosen.append(profile)
            seen.add(name)
    skips: list[Profile] = []
    if any(name == "all" for name in names):
        for profile in profiles:
            if profile.inherits_settings:
                skips.append(profile)
                continue
            if profile.name == source_name or profile.name in seen:
                continue
            chosen.append(profile)
            seen.add(profile.name)
    order = {profile.name: index for index, profile in enumerate(profiles)}
    chosen.sort(key=lambda profile: order[profile.name])
    return chosen, skips


def _selected_keys(
    source_values: Mapping[str, object],
    keys: Sequence[str],
    prefix: str | None,
) -> list[str]:
    wanted = set(keys)
    found: list[str] = []
    for key in sorted(source_values):
        if wanted and key not in wanted:
            continue
        if prefix is not None and not key.startswith(prefix):
            continue
        found.append(key)
    return found


def _plan_destination(
    profile: Profile,
    selected: Sequence[str],
    source_values: Mapping[str, object],
) -> _Planned:
    dest_values = read_own_settings(profile)
    original = _read_settings_text(profile)
    lines = tuple(
        _operation_line(profile.name, key, source_values, dest_values) for key in selected
    )
    changes = {
        key: source_values[key]
        for key in selected
        if key not in dest_values or not _same_value(dest_values[key], source_values[key])
    }
    replacing = {key for key in changes if key in dest_values}
    if not changes:
        return _Planned(profile, original, original, lines)
    try:
        new_text = edit_settings(original, changes, replacing)
    except CliError as exc:
        raise CliError(f"cannot edit settings for profile {profile.name!r}: {exc}") from exc
    return _Planned(profile, original, new_text, lines)


def _operation_line(
    name: str,
    key: str,
    source_values: Mapping[str, object],
    dest_values: Mapping[str, object],
) -> str:
    encoded = _dumps(source_values[key])
    if key not in dest_values:
        return f"{name}\t{key}\tadd\t{encoded}"
    if _same_value(dest_values[key], source_values[key]):
        return f"{name}\t{key}\tsame\t{encoded}"
    return f"{name}\t{key}\treplace\t{encoded}\t{_dumps(dest_values[key])}"


def _same_value(left: object, right: object) -> bool:
    return _dumps(left, sort_keys=True) == _dumps(right, sort_keys=True)


def _dumps(value: object, *, sort_keys: bool = False) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=sort_keys)


def _read_settings_text(profile: Profile) -> str:
    path = profile.settings_path
    try:
        return path.read_bytes().decode("utf-8")
    except OSError as exc:
        raise CliError(f"could not read settings.json: {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise CliError(f"settings.json is not UTF-8: {path}: {exc}") from exc


def _write_all(pending: Sequence[_Planned]) -> None:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f") + f"-{os.getpid()}"
    root = user_cache_dir() / "backups" / stamp
    staged: list[tuple[_Planned, Path]] = []
    for item in pending:
        folder = "Default" if item.profile.location is None else item.profile.location
        backup = root / folder / "settings.json"
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(item.original.encode("utf-8"))
        except OSError as exc:
            raise CliError(
                f"could not back up settings for profile {item.profile.name!r}: {exc}"
            ) from exc
        print(f"backup\t{item.profile.name}\t{backup}")
        staged.append((item, backup))
    for item, backup in staged:
        _commit_one(item, backup)


def _commit_one(item: _Planned, backup: Path) -> None:
    dest = item.profile.settings_path
    tmp = dest.with_name(dest.name + ".vscode-profiles-tmp")
    try:
        tmp.write_bytes(item.new_text.encode("utf-8"))
        commit_settings(tmp, dest)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        restored = _restore(backup, dest)
        print(f"restore\t{item.profile.name}\t{'ok' if restored else 'failed'}")
        raise CliError(
            f"could not write settings for profile {item.profile.name!r}: {exc}"
        ) from exc


def _restore(backup: Path, dest: Path) -> bool:
    try:
        dest.write_bytes(backup.read_bytes())
    except OSError:
        return False
    return True


@dataclass(frozen=True)
class _Document:
    keys: dict[str, tuple[int, int]]
    order: tuple[str, ...]
    close: int
    indent: str


def edit_settings(text: str, changes: Mapping[str, object], replacing: set[str]) -> str:
    if not changes:
        return text
    document = _scan(text)
    for key in replacing:
        if key not in document.keys:
            raise CliError(f"could not locate top-level key {key!r}")
    replacements = {key: value for key, value in changes.items() if key in document.keys}
    updated = _replace_values(text, document, replacements)
    additions = [(key, value) for key, value in sorted(changes.items()) if key not in document.keys]
    if not additions:
        return updated
    return _add_keys(_scan(updated), updated, additions)


def _replace_values(text: str, document: _Document, replacements: Mapping[str, object]) -> str:
    spans = [
        (document.keys[key][0], document.keys[key][1], _dumps(value))
        for key, value in replacements.items()
    ]
    for start, end, rendered in sorted(spans, reverse=True):
        text = text[:start] + rendered + text[end:]
    return text


def _add_keys(document: _Document, text: str, additions: list[tuple[str, object]]) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    close = document.close
    style_trailing = False
    if document.order:
        last_end = document.keys[document.order[-1]][1]
        if _gap_has_comma(text[last_end:close]):
            style_trailing = True
        else:
            text = text[:last_end] + "," + text[last_end:]
            close += 1
    lines: list[str] = []
    last_index = len(additions) - 1
    for index, (key, value) in enumerate(additions):
        comma = "," if style_trailing or index < last_index else ""
        lines.append(
            f"{document.indent}{json.dumps(key, ensure_ascii=False)}: {_dumps(value)}{comma}"
        )
    block = newline.join(lines)
    if text[:close].rstrip(" \t").endswith("\n"):
        insertion = block + newline
    else:
        insertion = newline + block + newline
    return text[:close] + insertion + text[close:]


def _gap_has_comma(gap: str) -> bool:
    scanner = _Scanner(gap)
    scanner.skip_ws_and_comments()
    return scanner.peek() == ","


def _detect_indent(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("\ufeff"):
            line = line[1:]
        stripped = line.lstrip(" \t")
        if stripped.startswith('"') and stripped != line:
            return line[: len(line) - len(stripped)]
    return "  "


def _scan(text: str) -> _Document:
    scanner = _Scanner(text)
    scanner.skip_ws_and_comments()
    if scanner.peek() == "\ufeff":
        scanner.i += 1
        scanner.skip_ws_and_comments()
    if scanner.peek() != "{":
        raise CliError("could not locate the top-level object")
    scanner.i += 1
    keys: dict[str, tuple[int, int]] = {}
    order: list[str] = []
    while True:
        scanner.skip_ws_and_comments()
        if scanner.peek() == "":
            raise CliError("could not locate the end of settings.json")
        if scanner.peek() == "}":
            close = scanner.i
            break
        if scanner.peek() != '"':
            raise CliError("could not locate a top-level key")
        key = scanner.read_string()
        if key in keys:
            raise CliError(f"duplicate top-level key {key!r}")
        scanner.skip_ws_and_comments()
        if scanner.peek() != ":":
            raise CliError(f"could not locate top-level key {key!r}")
        scanner.i += 1
        start, end = scanner.read_value_span()
        keys[key] = (start, end)
        order.append(key)
        scanner.skip_ws_and_comments()
        if scanner.peek() == ",":
            scanner.i += 1
    return _Document(keys, tuple(order), close, _detect_indent(text))


class _Scanner:
    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0
        self.n = len(text)

    def peek(self) -> str:
        if self.i >= self.n:
            return ""
        return self.text[self.i]

    def skip_ws_and_comments(self) -> None:
        while self.i < self.n:
            char = self.text[self.i]
            if char in " \t\r\n":
                self.i += 1
                continue
            if char == "/" and self.i + 1 < self.n and self.text[self.i + 1] == "/":
                self.i += 2
                while self.i < self.n and self.text[self.i] not in "\r\n":
                    self.i += 1
                continue
            if char == "/" and self.i + 1 < self.n and self.text[self.i + 1] == "*":
                self.i += 2
                while self.i + 1 < self.n and not (
                    self.text[self.i] == "*" and self.text[self.i + 1] == "/"
                ):
                    self.i += 1
                if self.i + 1 >= self.n:
                    raise CliError("unterminated block comment")
                self.i += 2
                continue
            return

    def read_string(self) -> str:
        start = self.i
        if self.peek() != '"':
            raise CliError("could not locate a string")
        self.i += 1
        escape = False
        while self.i < self.n:
            char = self.text[self.i]
            self.i += 1
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                return str(json.loads(self.text[start : self.i]))
        raise CliError("unterminated string")

    def read_value_span(self) -> tuple[int, int]:
        self.skip_ws_and_comments()
        start = self.i
        char = self.peek()
        if char == '"':
            self.read_string()
        elif char == "{":
            self.skip_container("{", "}")
        elif char == "[":
            self.skip_container("[", "]")
        elif char == "-" or char.isdigit():
            self.skip_number()
        elif self.text.startswith("true", self.i):
            self.i += 4
        elif self.text.startswith("false", self.i):
            self.i += 5
        elif self.text.startswith("null", self.i):
            self.i += 4
        else:
            raise CliError("could not locate a value")
        return start, self.i

    def skip_container(self, open_char: str, close_char: str) -> None:
        if self.peek() != open_char:
            raise CliError("could not locate a value")
        self.i += 1
        depth = 1
        while self.i < self.n and depth:
            char = self.text[self.i]
            if char == '"':
                self.read_string()
                continue
            if char == "/" and self.i + 1 < self.n and self.text[self.i + 1] in "/*":
                self.skip_ws_and_comments()
                continue
            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
            self.i += 1
        if depth != 0:
            raise CliError("could not locate a value")

    def skip_number(self) -> None:
        while self.i < self.n and self.text[self.i] in "0123456789eE+-.":
            self.i += 1
