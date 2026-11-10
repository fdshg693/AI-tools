r"""Single entry point that dispatches to the Tavily wrapper scripts.

Installed as the ``tav`` console command (see ``./pyproject.toml``), so the long
``python .\tools\tav-cli\<script>.py ...`` invocations collapse to
short subcommands:

    tav search "Microsoft Fabric overview" --detail balanced --topic fabric_overview
    tav extract https://learn.microsoft.com/azure/api-management/ --query "..." --topic apim
    tav crawl  https://learn.microsoft.com/azure/api-management/ --query "..." --topic apim

This is a thin router only: it maps a subcommand name to one wrapper module and
forwards the remaining arguments to that module's ``main(argv)``, then hands the
returned ``RunOutcome`` to the shared ``finalize()`` shell — the per-script CLI
arguments, presets and output contract are unchanged. Run ``tav`` (or ``tav
--help``) to list subcommands, and ``tav <subcommand> --help`` for one script's
own arguments.
"""

from __future__ import annotations

import importlib
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from tav_core import ExitCode, environment, finalize
from tav_core.environment import TAV_CLI_ROOT


# subcommand -> (wrapper module name, role tag, one-line summary). The module
# names match the files in this directory; each exposes ``main(argv) -> RunOutcome``.
# The role tag mirrors the topic-folder layout (PLAN.md §4): discovery files an
# aggregated list under search/ or map/, content writes one .md page per URL under
# pages/, report writes one .md under research/. Composites do both.
SUBCOMMANDS: dict[str, tuple[str, str, str]] = {
    "search": ("search_topic", "discovery", "keyword -> related URLs + snippets"),
    "search-extract": (
        "search_extract_topic",
        "discovery+content",
        "keyword -> URLs, then extract their content",
    ),
    "research": (
        "research_topic",
        "report",
        "hand a question to Tavily research, wait for the report",
    ),
    "extract": ("extract_url_content", "content", "known URL(s) -> page content"),
    "map": ("map_site_titles", "discovery", "site root -> URL list with titles"),
    "map-extract": (
        "map_extract_site_content",
        "discovery+content",
        "map a site, then extract chosen URLs",
    ),
    "crawl": ("crawl_site_content", "content", "crawl a site -> related page content"),
}


def tool_version() -> str:
    data = tomllib.loads((TAV_CLI_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


def show_config() -> int:
    """`tav config`: どの設定ファイルを読み、各設定値がどこから来たかを表示する。"""
    try:
        files = environment.load_config_files()
    except environment.ConfigError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return int(ExitCode.RUNTIME_ERROR)
    git_root = environment.find_git_root()
    lines = [
        f"cwd:            {Path.cwd()}",
        f"git root:       {git_root or '(git 管理外)'}",
        f"global config:  {environment.global_config_path()}",
        "loaded files (precedence order):",
        *([f"  [{f.scope}] {f.path}" for f in files] or ["  (なし)"]),
        "settings:",
    ]
    for key in environment.SETTINGS:
        setting = environment.resolve_setting(key)
        if key == "api_key":
            shown = "(set)" if environment.get_normalized_api_key() else "(missing)"
        elif key == "output_dir":
            shown = str(environment.get_output_dir())
        elif key == "log_dir":
            shown = str(environment.get_log_dir())
        else:
            shown = str(setting.value) if setting.value is not None else "(default: true)"
        lines.append(f"  {key} = {shown}  <- {setting.source}")
    print("\n".join(lines))
    return 0


def render_usage() -> str:
    name_width = max(len(name) for name in SUBCOMMANDS)
    role_width = max(len(role) for _name, (_m, role, _s) in SUBCOMMANDS.items())
    lines = ["Usage: tav <subcommand> [args...]", "", "Subcommands (role = topic-folder layout):"]
    lines += [
        f"  {name.ljust(name_width)}  [{role.ljust(role_width)}]  {summary}"
        for name, (_m, role, summary) in SUBCOMMANDS.items()
    ]
    lines += [
        "",
        "Run 'tav <subcommand> --help' for that subcommand's own arguments.",
        "Run 'tav config' to show which config files and settings are in effect.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args == ["--version"]:
        print(f"tav {tool_version()}")
        return 0

    if not args or args[0] in ("-h", "--help"):
        print(render_usage())
        return int(ExitCode.SUCCESS)

    name = args[0]
    if name == "config":
        return show_config()
    entry = SUBCOMMANDS.get(name)
    if entry is None:
        print(f"Unknown subcommand: {name}\n", file=sys.stderr)
        print(render_usage(), file=sys.stderr)
        return int(ExitCode.RUNTIME_ERROR)

    module = importlib.import_module(entry[0])
    return int(finalize(module.main(args[1:])))


if __name__ == "__main__":
    raise SystemExit(main())
