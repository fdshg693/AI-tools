"""Per-agent hook registration: build entries and merge them into agent config files.

Each agent registers command hooks in its own JSON file with its own nesting:

- claude (``.claude/settings.json``) and codex (``.codex/hooks.json``):
  ``hooks.<event>[] = {matcher?, hooks: [<entry>]}``
- cursor (``.cursor/hooks.json``): ``{version: 1, hooks: {<event>: [<entry>]}}``
  with ``matcher`` inside the entry
- antigravity (``.agents/hooks.json``): ``<hook-name>.<event>[]`` holding
  ``{matcher, hooks: [<entry>]}`` when a matcher is given, else the entry itself
- kilo: no registration file; placing the plugin enables it

With ``--global`` the files go under the home directory and the user-wide
registration files are edited instead (``~/.claude/settings.json``,
``~/.codex/hooks.json``, ``~/.cursor/hooks.json``). Their command lines name
the placed file by absolute path (Cursor: relative to ``~/.cursor/``), computed
once at install time. Antigravity has no known user-wide hook file and is
refused.

skill-tools owns only the entries it inserted. They are identified by the
SHA-256 of their canonical JSON, recorded in the manifest, so removal never
touches a user's own entries even when they sit in the same matcher group.
Unknown keys are preserved; the file is rewritten with two-space indentation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any

from ..config import CLAUDE_SETTINGS_FILES, HooksConfig
from ..models import InstallError

DEFAULT_INSTALL_DIRS = {
    "claude": ".claude/hooks",
    "codex": ".codex/hooks",
    "cursor": ".cursor/hooks",
    "antigravity": ".agents/hooks",
    "kilo": ".kilo/plugin",
}
_REGISTRATION_FILES = {
    "codex": ".codex/hooks.json",
    "cursor": ".cursor/hooks.json",
    "antigravity": ".agents/hooks.json",
}
GLOBAL_INSTALL_DIRS = {
    "claude": ".claude/hooks",
    "codex": ".codex/hooks",
    "cursor": ".cursor/hooks",
    "kilo": ".config/kilo/plugin",
}
"""Home-relative hook directories for ``--global``; agents missing here are refused."""
_GLOBAL_REGISTRATION_FILES = {
    "claude": ".claude/settings.json",
    "codex": ".codex/hooks.json",
    "cursor": ".cursor/hooks.json",
}
_CURSOR_HOME = ".cursor/"
_GIT_ROOT = "$(git rev-parse --show-toplevel)"
_GIT_ROOT_PS = "(git rev-parse --show-toplevel)"


def supports_global(agent: str) -> bool:
    return agent in GLOBAL_INSTALL_DIRS


def install_dir_for(agent: str, config: HooksConfig, *, global_scope: bool = False) -> str:
    if global_scope:
        if not supports_global(agent):
            raise InstallError(f"{agent} hooks cannot be installed with --global")
        return config.global_destinations.get(agent, GLOBAL_INSTALL_DIRS[agent])
    return config.destinations.get(agent, DEFAULT_INSTALL_DIRS[agent])


def registration_file_for(
    agent: str, config: HooksConfig, *, global_scope: bool = False
) -> str | None:
    """Root-relative registration file for ``agent``; ``None`` for kilo.

    With ``global_scope`` the path is home-relative and ``settings_file: local``
    is ignored (Claude Code has no user-wide ``settings.local.json``).
    """

    if global_scope:
        return _GLOBAL_REGISTRATION_FILES.get(agent)
    if agent == "claude":
        return CLAUDE_SETTINGS_FILES[config.claude_settings_file]
    return _REGISTRATION_FILES.get(agent)


def entry_hash(entry: dict[str, Any]) -> str:
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_SHELL_SPECIAL = re.compile(r"""[\s"'`$&|;<>()*?!#~{}\[\]%^,]""")


def _quote(path: str) -> str:
    """Double-quote a path for a one-string command line when it needs it.

    Plain relative paths stay unquoted so existing entries (and their hashes)
    do not change. Paths with a double quote cannot be expressed safely.
    """

    if '"' in path:
        raise InstallError(f"hook path contains a double quote: {path}")
    return f'"{path}"' if _SHELL_SPECIAL.search(path) else path


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def command_path(agent: str, main_path: str, home: Path | None = None) -> str:
    """The hook file path as it appears in the agent's command line.

    Project scope: ``main_path`` itself (root-relative POSIX). Global scope
    (``home`` given): an absolute POSIX path, or for Cursor a path relative to
    ``~/.cursor/`` when the file lies inside it.
    """

    if home is None:
        return main_path
    if agent == "cursor" and main_path.startswith(_CURSOR_HOME):
        return main_path[len(_CURSOR_HOME) :]
    return (PurePosixPath(home.resolve().as_posix()) / main_path).as_posix()


def _runner_words(runner: str, project: str) -> list[str]:
    if runner == "uv-script":
        return ["uv", "run", "--script"]
    if runner == "uv-project":
        return ["uv", "run", "--project", project]
    return ["python"]


def _command_fields(agent: str, runner: str, main_path: str) -> dict[str, Any]:
    """Build the command part of an entry; ``main_path`` is project-relative POSIX."""

    if agent == "claude":
        words = _runner_words(runner, "${CLAUDE_PROJECT_DIR}")
        return {
            "type": "command",
            "command": words[0],
            "args": [*words[1:], f"${{CLAUDE_PROJECT_DIR}}/{main_path}"],
        }
    if agent == "codex":
        # Codex runs hooks from the session CWD, so anchor on the git top level.
        posix = {"python": ["python3"]}.get(runner) or _runner_words(runner, f'"{_GIT_ROOT}"')
        windows = {"python": ["python"]}.get(runner) or _runner_words(runner, _GIT_ROOT_PS)
        return {
            "type": "command",
            "command": " ".join([*posix, f'"{_GIT_ROOT}/{main_path}"']),
            "commandWindows": "powershell -NoProfile -Command "
            + '"'
            + " ".join([*windows, f"(Join-Path {_GIT_ROOT_PS} '{main_path}')"])
            + '"',
        }
    command = " ".join([*_runner_words(runner, "."), _quote(main_path)])
    if agent == "cursor":
        return {"command": command}
    return {"type": "command", "command": command}


def _global_command_fields(agent: str, runner: str, main_path: str, home: Path) -> dict[str, Any]:
    """Command part of a ``--global`` entry: the placed file by absolute path."""

    path = command_path(agent, main_path, home)
    home_posix = home.resolve().as_posix()
    if agent == "claude":
        words = _runner_words(runner, home_posix)
        return {"type": "command", "command": words[0], "args": [*words[1:], path]}
    if agent == "codex":
        posix = ["python3"] if runner == "python" else _runner_words(runner, _sh_quote(home_posix))
        windows = ["python"] if runner == "python" else _runner_words(runner, _ps_quote(home_posix))
        return {
            "type": "command",
            "command": " ".join([*posix, _sh_quote(path)]),
            "commandWindows": "powershell -NoProfile -Command "
            + '"'
            + " ".join([*windows, _ps_quote(path)])
            + '"',
        }
    if agent == "cursor":
        return {"command": " ".join([*_runner_words(runner, _quote(home_posix)), _quote(path)])}
    raise InstallError(f"{agent} hooks cannot be registered with --global")


def build_entry(
    agent: str,
    runner: str,
    main_path: str,
    registration: dict,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """The hook entry skill-tools inserts (and later identifies by hash).

    ``main_path`` is root-relative POSIX. ``home`` selects the ``--global``
    form, where the command names the placed file under ``home`` by absolute path.
    """

    entry = (
        _command_fields(agent, runner, main_path)
        if home is None
        else _global_command_fields(agent, runner, main_path, home)
    )
    for key, value in registration.items():
        if key == "event" or (key == "matcher" and agent != "cursor"):
            continue
        entry[key] = value
    return entry


def _command_texts(value: Any) -> Iterator[tuple[dict, str]]:
    """Every command-like dict in a registration document, with its command line."""

    if isinstance(value, dict):
        command = value.get("command")
        if isinstance(command, str):
            args = value.get("args")
            words = (
                [command, *(a for a in args if isinstance(a, str))]
                if isinstance(args, list)
                else [command]
            )
            yield value, " ".join([*words, str(value.get("commandWindows", ""))])
        for child in value.values():
            yield from _command_texts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _command_texts(child)


class RegistrationDocument:
    """One agent registration file loaded for editing."""

    def __init__(self, agent: str, relative: str, raw: bytes | None) -> None:
        self.agent = agent
        self.relative = relative
        self.raw = raw
        if raw is None or not raw.strip():
            self.data: dict[str, Any] = {}
        else:
            try:
                data = json.loads(raw.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise InstallError(
                    f"{relative} is not plain JSON (comments/JSONC are not supported); "
                    f"refusing to edit it: {exc}"
                ) from exc
            if not isinstance(data, dict):
                raise InstallError(f"{relative} must contain a JSON object")
            self.data = data
        self.changed = False

    # -- locating the event list -------------------------------------------------

    def _container(self, hook_id: str, create: bool) -> dict[str, Any] | None:
        """The mapping whose keys are event names."""

        if self.agent == "antigravity":
            key = hook_id.replace("_", "-")
        else:
            key = "hooks"
            if self.agent == "cursor" and create:
                self.data.setdefault("version", 1)
        container = self.data.get(key)
        if container is None:
            if not create:
                return None
            container = self.data[key] = {}
        if not isinstance(container, dict):
            raise InstallError(f"{self.relative}: {key!r} must be a JSON object")
        return container

    def _events(self, hook_id: str, event: str, create: bool) -> list | None:
        container = self._container(hook_id, create)
        if container is None:
            return None
        events = container.get(event)
        if events is None:
            if not create:
                return None
            events = container[event] = []
        if not isinstance(events, list):
            raise InstallError(f"{self.relative}: hooks for {event!r} must be a JSON array")
        return events

    def _grouped(self, matcher: str | None) -> bool:
        return self.agent in {"claude", "codex"} or (
            self.agent == "antigravity" and matcher is not None
        )

    # -- editing -------------------------------------------------------------------

    def add(self, hook_id: str, event: str, matcher: str | None, entry: dict) -> None:
        events = self._events(hook_id, event, create=True)
        assert events is not None
        if self._grouped(matcher):
            group = next(
                (
                    item
                    for item in events
                    if isinstance(item, dict)
                    and item.get("matcher") == matcher
                    and isinstance(item.get("hooks"), list)
                ),
                None,
            )
            if group is None:
                group = {"matcher": matcher, "hooks": []} if matcher is not None else {"hooks": []}
                events.append(group)
            group["hooks"].append(entry)
        else:
            events.append(entry)
        self.changed = True

    def remove(self, hook_id: str, event: str, matcher: str | None, digest: str) -> bool:
        """Remove the last entry with ``digest``; prune what becomes empty."""

        events = self._events(hook_id, event, create=False)
        if events is None:
            return False
        grouped = self._grouped(matcher)
        for index in range(len(events) - 1, -1, -1):
            item = events[index]
            if grouped:
                if not (isinstance(item, dict) and item.get("matcher") == matcher):
                    continue
                inner = item.get("hooks")
                if not isinstance(inner, list):
                    continue
                for position in range(len(inner) - 1, -1, -1):
                    if isinstance(inner[position], dict) and entry_hash(inner[position]) == digest:
                        del inner[position]
                        if not inner:
                            del events[index]
                        self._prune(hook_id, event)
                        return True
            elif isinstance(item, dict) and entry_hash(item) == digest:
                del events[index]
                self._prune(hook_id, event)
                return True
        return False

    def _prune(self, hook_id: str, event: str) -> None:
        self.changed = True
        container = self._container(hook_id, create=False)
        assert container is not None
        if not container[event]:
            del container[event]
        if not container:
            key = hook_id.replace("_", "-") if self.agent == "antigravity" else "hooks"
            del self.data[key]

    def foreign_commands(self, needle: str, owned: set[str]) -> list[str]:
        """Command lines not owned by skill-tools that mention ``needle``."""

        return [
            text
            for item, text in _command_texts(self.data)
            if needle in text.replace("\\", "/") and entry_hash(item) not in owned
        ]

    def content(self) -> bytes | None:
        """New file bytes, or ``None`` when the file should be deleted."""

        empty = not self.data or (self.agent == "cursor" and set(self.data) == {"version"})
        if empty:
            return None
        text = json.dumps(self.data, ensure_ascii=False, indent=2) + "\n"
        return text.encode("utf-8")
