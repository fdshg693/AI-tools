from __future__ import annotations

import json

import pytest

from skill_tools.config import HooksConfig
from skill_tools.hooks.registrars import (
    RegistrationDocument,
    build_entry,
    entry_hash,
    install_dir_for,
    registration_file_for,
    supports_global,
)
from skill_tools.models import InstallError


def test_default_locations_and_claude_settings_file_switch() -> None:
    config = HooksConfig()
    assert install_dir_for("antigravity", config) == ".agents/hooks"
    assert install_dir_for("kilo", config) == ".kilo/plugin"
    assert registration_file_for("claude", config) == ".claude/settings.json"
    assert registration_file_for("kilo", config) is None
    local = HooksConfig(claude_settings_file="local", destinations={"codex": "tools/hooks"})
    assert registration_file_for("claude", local) == ".claude/settings.local.json"
    assert install_dir_for("codex", local) == "tools/hooks"


@pytest.mark.parametrize(
    ("runner", "command", "args"),
    [
        ("python", "python", ["${CLAUDE_PROJECT_DIR}/.claude/hooks/x.py"]),
        ("uv-script", "uv", ["run", "--script", "${CLAUDE_PROJECT_DIR}/.claude/hooks/x.py"]),
        (
            "uv-project",
            "uv",
            [
                "run",
                "--project",
                "${CLAUDE_PROJECT_DIR}",
                "${CLAUDE_PROJECT_DIR}/.claude/hooks/x.py",
            ],
        ),
    ],
)
def test_claude_entry_uses_command_and_args(runner: str, command: str, args: list[str]) -> None:
    entry = build_entry(
        "claude", runner, ".claude/hooks/x.py", {"event": "Stop", "matcher": "*", "timeout": 5}
    )

    assert entry == {"type": "command", "command": command, "args": args, "timeout": 5}


def test_codex_entry_anchors_on_git_top_level_for_both_shells() -> None:
    entry = build_entry(
        "codex", "python", ".codex/hooks/x.py", {"event": "SessionStart", "statusMessage": "hi"}
    )

    assert entry == {
        "type": "command",
        "command": 'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/x.py"',
        "commandWindows": 'powershell -NoProfile -Command "python (Join-Path '
        "(git rev-parse --show-toplevel) '.codex/hooks/x.py')\"",
        "statusMessage": "hi",
    }
    uv = build_entry("codex", "uv-script", ".codex/hooks/x.py", {"event": "Stop"})
    assert uv["command"].startswith("uv run --script ")


def test_cursor_keeps_matcher_in_entry_and_adds_version() -> None:
    document = RegistrationDocument("cursor", ".cursor/hooks.json", None)
    entry = build_entry(
        "cursor", "python", ".cursor/hooks/x.py", {"event": "postToolUse", "matcher": "Read"}
    )
    document.add("x", "postToolUse", "Read", entry)

    assert entry == {"command": "python .cursor/hooks/x.py", "matcher": "Read"}
    assert json.loads(document.content()) == {"version": 1, "hooks": {"postToolUse": [entry]}}
    assert document.remove("x", "postToolUse", "Read", entry_hash(entry))
    assert document.content() is None


def test_antigravity_groups_only_matched_events_under_the_hook_name() -> None:
    document = RegistrationDocument("antigravity", ".agents/hooks.json", b'{"mine": {"Stop": []}}')
    matched = build_entry("antigravity", "python", ".agents/hooks/a_b.py", {"event": "PreToolUse"})
    plain = build_entry("antigravity", "python", ".agents/hooks/a_b.py", {"event": "Stop"})
    document.add("a_b", "PreToolUse", "run_command", matched)
    document.add("a_b", "Stop", None, plain)

    data = json.loads(document.content())
    assert data["mine"] == {"Stop": []}
    assert data["a-b"] == {
        "PreToolUse": [{"matcher": "run_command", "hooks": [matched]}],
        "Stop": [plain],
    }
    assert document.remove("a_b", "PreToolUse", "run_command", entry_hash(matched))
    assert document.remove("a_b", "Stop", None, entry_hash(plain))
    assert json.loads(document.content()) == {"mine": {"Stop": []}}


def test_claude_merges_into_existing_group_and_removes_only_its_entry() -> None:
    user = {"type": "command", "command": "echo mine"}
    raw = json.dumps(
        {"env": {"A": "1"}, "hooks": {"PreToolUse": [{"matcher": "Read", "hooks": [user]}]}}
    ).encode()
    document = RegistrationDocument("claude", ".claude/settings.json", raw)
    ours = build_entry("claude", "python", ".claude/hooks/x.py", {"event": "PreToolUse"})

    document.add("x", "PreToolUse", "Read", ours)
    document.add("x", "CwdChanged", None, ours)
    data = json.loads(document.content())
    assert data["hooks"]["PreToolUse"] == [{"matcher": "Read", "hooks": [user, ours]}]
    assert data["hooks"]["CwdChanged"] == [{"hooks": [ours]}]

    assert document.remove("x", "PreToolUse", "Read", entry_hash(ours))
    assert document.remove("x", "CwdChanged", None, entry_hash(ours))
    assert not document.remove("x", "CwdChanged", None, entry_hash(ours))
    assert json.loads(document.content()) == json.loads(raw)


def test_edited_entry_is_not_removed() -> None:
    ours = build_entry("claude", "python", ".claude/hooks/x.py", {"event": "Stop"})
    edited = {**ours, "timeout": 99}
    raw = json.dumps({"hooks": {"Stop": [{"hooks": [edited]}]}}).encode()
    document = RegistrationDocument("claude", ".claude/settings.json", raw)

    assert not document.remove("x", "Stop", None, entry_hash(ours))
    assert document.foreign_commands(".claude/hooks/x.py", set()) == [
        "python ${CLAUDE_PROJECT_DIR}/.claude/hooks/x.py "
    ]
    assert document.foreign_commands(".claude/hooks/x.py", {entry_hash(edited)}) == []


@pytest.mark.parametrize("raw", [b'{\n  // comment\n  "hooks": {}\n}', b"[1]", b'{"hooks": []}'])
def test_unsupported_documents_are_rejected(raw: bytes) -> None:
    with pytest.raises(InstallError):
        document = RegistrationDocument("claude", ".claude/settings.json", raw)
        document.add("x", "Stop", None, {"type": "command", "command": "x"})


# --- --global -----------------------------------------------------------------


def test_global_locations_ignore_project_settings() -> None:
    config = HooksConfig(
        claude_settings_file="local",
        destinations={"claude": "tools/hooks"},
        global_destinations={"codex": ".codex/my-hooks"},
    )
    assert install_dir_for("claude", config, global_scope=True) == ".claude/hooks"
    assert install_dir_for("codex", config, global_scope=True) == ".codex/my-hooks"
    assert install_dir_for("kilo", config, global_scope=True) == ".config/kilo/plugin"
    assert registration_file_for("claude", config, global_scope=True) == ".claude/settings.json"
    assert registration_file_for("kilo", config, global_scope=True) is None
    assert not supports_global("antigravity")
    with pytest.raises(InstallError, match="--global"):
        install_dir_for("antigravity", config, global_scope=True)


def test_global_claude_entry_uses_absolute_paths(tmp_path) -> None:
    home = tmp_path / "my home"
    home.mkdir()
    absolute = f"{home.resolve().as_posix()}/.claude/hooks/x.py"
    entry = build_entry("claude", "python", ".claude/hooks/x.py", {"event": "Stop"}, home=home)
    assert entry == {"type": "command", "command": "python", "args": [absolute]}
    project = build_entry(
        "claude", "uv-project", ".claude/hooks/x.py", {"event": "Stop"}, home=home
    )
    assert project["args"] == ["run", "--project", home.resolve().as_posix(), absolute]


def test_global_codex_entry_quotes_for_both_shells(tmp_path) -> None:
    home = tmp_path / "O'Neil home"
    home.mkdir()
    absolute = f"{home.resolve().as_posix()}/.codex/hooks/x.py"
    entry = build_entry("codex", "python", ".codex/hooks/x.py", {"event": "Stop"}, home=home)
    sh = "'" + absolute.replace("'", "'\\''") + "'"
    ps = "'" + absolute.replace("'", "''") + "'"
    assert entry == {
        "type": "command",
        "command": f"python3 {sh}",
        "commandWindows": f'powershell -NoProfile -Command "python {ps}"',
    }


def test_global_cursor_entry_is_relative_to_dot_cursor(tmp_path) -> None:
    entry = build_entry(
        "cursor",
        "python",
        ".cursor/hooks/x.py",
        {"event": "stop", "matcher": "Read"},
        home=tmp_path,
    )
    assert entry == {"command": "python hooks/x.py", "matcher": "Read"}
    outside = build_entry("cursor", "python", "my hooks/x.py", {"event": "stop"}, home=tmp_path)
    assert outside == {"command": f'python "{tmp_path.resolve().as_posix()}/my hooks/x.py"'}


def test_project_entries_keep_their_command_text() -> None:
    # Widening the quoting rules must not change (and so re-hash) plain project entries.
    entry = build_entry("cursor", "python", ".cursor/hooks/x.py", {"event": "stop"})
    assert entry == {"command": "python .cursor/hooks/x.py"}
    spaced = build_entry("antigravity", "python", "my hooks/x.py", {"event": "PreInvocation"})
    assert spaced["command"] == 'python "my hooks/x.py"'
    with pytest.raises(InstallError, match="double quote"):
        build_entry("cursor", "python", 'a"b/x.py', {"event": "stop"})
