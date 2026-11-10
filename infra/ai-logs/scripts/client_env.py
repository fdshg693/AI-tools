#!/usr/bin/env python3
"""Manage the Claude Code -> ai-logs OTLP client env vars on this dev machine.

Reads SERVER_IP / OTLP_AUTH_TOKEN from tools/infra/ai-logs/.env and derives the
CLAUDE_CODE_* / OTEL_* env vars documented in ../README.md ("収集対象ツールの
クライアント設定" section). Three subcommands:

  emit    - print export/$env: statements to stdout, for the CURRENT shell only.
            A child process (this script) cannot mutate its parent shell's
            environment, so the caller must eval/dot-source the output.
  install - set the vars as persistent Windows User environment variables
            (HKCU\\Environment via [Environment]::SetEnvironmentVariable).
  purge   - remove those Windows User environment variables, and print
            unset statements for the CURRENT shell.

install/purge used to append/remove a managed block in the shell profile
(~/.bashrc or pwsh's $PROFILE), but that only takes effect for shells that
source the profile at startup -- GUI-launched apps (e.g. VS Code opened from
the Start Menu/taskbar, not from an already-profiled terminal) never see it.
Windows User env vars apply to any new process regardless of how it was
launched. Any leftover managed block from the old approach is cleaned up by
install/purge too. Either way, already-running processes (an open VS Code
window, an already-running `claude`) must be fully restarted to pick up the
change -- env vars are only inherited at process creation.

Invoked via `just env-emit` / `just env-install` / `just env-purge` (see justfile).
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # tools/infra/ai-logs
ENV_FILE = ROOT / ".env"

MARK_BEGIN = "# >>> ai-logs client env (managed by tools/infra/ai-logs/scripts/client_env.py) >>>"
MARK_END = "# <<< ai-logs client env <<<"

REQUIRED_KEYS = ("SERVER_IP", "OTLP_AUTH_TOKEN")


def load_env_file(path):
    if not path.is_file():
        sys.exit(
            f"error: {path} not found. Copy .env.example to .env and fill in "
            f"{'/'.join(REQUIRED_KEYS)} (see `just ip` / `just show-secrets`)."
        )
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    missing = [k for k in REQUIRED_KEYS if not values.get(k)]
    if missing:
        sys.exit(f"error: {path} is missing values for: {', '.join(missing)}")
    return values


def derive_vars(env):
    server_ip = env["SERVER_IP"]
    token = env["OTLP_AUTH_TOKEN"]
    return {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
        "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://{server_ip}:4317",
        "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization=Bearer {token}",
    }


def render_set(shell, v):
    if shell == "bash":
        return "\n".join(f'export {k}="{val}"' for k, val in v.items())
    return "\n".join(f'$env:{k} = "{val}"' for k, val in v.items())


def render_unset(shell, v):
    if shell == "bash":
        return "unset " + " ".join(v.keys())
    return "\n".join(f"Remove-Item Env:\\{k} -ErrorAction SilentlyContinue" for k in v.keys())


def profile_path(shell):
    if shell == "bash":
        home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
        if not home:
            sys.exit("error: could not determine $HOME for bash profile lookup")
        return Path(home) / ".bashrc"
    # pwsh: ask pwsh itself for $PROFILE (exact path differs by version/host/OS)
    try:
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", "$PROFILE"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        sys.exit(f"error: could not resolve pwsh $PROFILE: {e}")
    return Path(result.stdout.strip())


def remove_stale_profile_blocks():
    """Remove any managed block left over from the old shell-profile approach."""
    removed = []
    for shell in ("bash", "pwsh"):
        try:
            path = profile_path(shell)
        except SystemExit:
            continue
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if MARK_BEGIN in text and MARK_END in text:
            start = text.index(MARK_BEGIN)
            end = text.index(MARK_END) + len(MARK_END)
            text = text[:start] + text[end:]
            path.write_text(text, encoding="utf-8")
            removed.append(path)
    return removed


def _pwsh_escape(value):
    # Escape for embedding inside a PowerShell double-quoted string literal.
    return value.replace("`", "``").replace("$", "`$").replace('"', '`"')


def _run_pwsh(script):
    try:
        subprocess.run(["pwsh", "-NoProfile", "-Command", script], check=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        sys.exit(f"error: failed to run pwsh: {e}")


def set_user_env_vars(v):
    stmts = "; ".join(
        f'[Environment]::SetEnvironmentVariable("{k}", "{_pwsh_escape(val)}", "User")'
        for k, val in v.items()
    )
    _run_pwsh(stmts)


def unset_user_env_vars(v):
    stmts = "; ".join(
        f'[Environment]::SetEnvironmentVariable("{k}", $null, "User")' for k in v.keys()
    )
    _run_pwsh(stmts)


def cmd_emit(args, v):
    print(render_set(args.shell, v))


def cmd_install(args, v):
    set_user_env_vars(v)
    print("set as persistent Windows User environment variables:")
    for k in v:
        print(f"  {k}")
    for path in remove_stale_profile_blocks():
        print(f"removed stale shell-profile block from {path} (superseded by the above)")
    print(
        "fully restart any already-running app that should pick this up "
        "(e.g. quit and reopen VS Code) -- already-running processes keep "
        "the environment they started with"
    )


def cmd_purge(args, v):
    unset_user_env_vars(v)
    print("removed from Windows User environment variables:", ", ".join(v.keys()))
    for path in remove_stale_profile_blocks():
        print(f"removed stale shell-profile block from {path}")
    print("run this in your CURRENT shell to unset the variables now:")
    print(render_unset(args.shell, v))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="action", required=True)
    for name, fn in (("emit", cmd_emit), ("install", cmd_install), ("purge", cmd_purge)):
        p = sub.add_parser(name)
        p.add_argument("--shell", choices=["bash", "pwsh"], default="pwsh")
        p.set_defaults(func=fn)

    args = parser.parse_args()
    env = load_env_file(ENV_FILE)
    v = derive_vars(env)
    args.func(args, v)


if __name__ == "__main__":
    main()
