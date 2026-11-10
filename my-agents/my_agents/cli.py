"""YAML定義のエージェントを実行・管理するCLI(Typer)。"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import typer
import yaml

from .agent import run_agent
from .config import load_agent_config
from .tools import TOOL_REGISTRY

# 実行時のカレントディレクトリに依存せず、常にこのパッケージが置かれた
# tools/my-agents/agents/ を参照する。
TOOL_DIR = Path(__file__).resolve().parent.parent
AGENTS_DIR = TOOL_DIR / "agents"

app = typer.Typer(
    name="my-agents",
    help="YAML定義のLangchainエージェントを実行・管理するCLI",
    no_args_is_help=True,
    add_completion=False,
)


def tool_version() -> str:
    data = tomllib.loads((TOOL_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


def _resolve_agent_config_path(config: str) -> Path:
    """`config`を設定YAMLのパスとして解決する。

    既存パスとして存在すればそれを使う。存在しない場合はagents/配下のYAMLを
    総当たりし、`name`フィールドが一致した最初のファイルを使う(name重複時は
    無視して最初に見つかったものを使う)。
    """
    path = Path(config)
    if path.exists():
        return path

    if AGENTS_DIR.exists():
        candidates = sorted(set(AGENTS_DIR.glob("*.yaml")) | set(AGENTS_DIR.glob("*.yml")))
        for candidate in candidates:
            try:
                agent_config = load_agent_config(candidate)
            except Exception:  # noqa: BLE001 - 読み込めない設定は候補から無視する
                continue
            if agent_config.name == config:
                return candidate

    typer.secho(
        f"エラー: 設定ファイルもエージェント名も見つかりません: {config}",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(code=1)


@app.command()
def run(
    config: str = typer.Argument(
        ...,
        help="エージェント設定YAMLのパス、またはエージェント名(agents/配下のnameと一致するもの)",
    ),
    prompt: str = typer.Option(
        None, "--prompt", help="ユーザープロンプト。省略時は標準入力から読み込む"
    ),
) -> None:
    """エージェント設定YAMLまたはエージェント名を指定してエージェントを実行する。"""
    if prompt is None:
        prompt = sys.stdin.read().strip()
    if not prompt:
        typer.secho(
            "エラー: --prompt か標準入力のいずれかでプロンプトを指定してください",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    config_path = _resolve_agent_config_path(config)
    agent_config = load_agent_config(config_path)
    try:
        answer, log_path = run_agent(agent_config, prompt)
    except Exception as exc:  # noqa: BLE001 - CLIとしてエラー内容をそのまま伝える
        typer.secho(f"エラー: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.secho(f"log: {log_path}", fg=typer.colors.CYAN, err=True)
    typer.echo(answer)


@app.command("list-tools")
def list_tools(
    format: str = typer.Option("text", "--format", help="出力形式: text(既定) または yaml"),
    output: Path = typer.Option(None, "--output", help="出力先パス。省略時は標準出力に書き出す"),
) -> None:
    """利用可能なツール(TOOL_REGISTRY)の一覧を表示する。"""
    if format not in ("text", "yaml"):
        typer.secho(
            f"エラー: 未知の --format です: {format} (text または yaml)",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    if format == "text":
        content = "\n".join(
            f"{name}: {TOOL_REGISTRY[name].description or ''}" for name in sorted(TOOL_REGISTRY)
        )
    else:
        tools_data = [
            {
                "name": name,
                "description": TOOL_REGISTRY[name].description or "",
                "args": TOOL_REGISTRY[name].args,
            }
            for name in sorted(TOOL_REGISTRY)
        ]
        content = yaml.safe_dump(tools_data, allow_unicode=True, sort_keys=False)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        typer.echo(f"書き出しました: {output}")
    else:
        typer.echo(content)


@app.command("list-agents")
def list_agents() -> None:
    """agents/ 配下のエージェント設定YAMLの一覧を表示する。"""
    if not AGENTS_DIR.exists():
        typer.echo(f"エージェントディレクトリが見つかりません: {AGENTS_DIR}")
        raise typer.Exit(code=1)

    paths = sorted(set(AGENTS_DIR.glob("*.yaml")) | set(AGENTS_DIR.glob("*.yml")))
    if not paths:
        typer.echo(f"エージェント設定YAMLが見つかりません: {AGENTS_DIR}")
        return

    for path in paths:
        try:
            agent_config = load_agent_config(path)
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"{path.name}: 読み込みエラー ({exc})")
            continue
        tools = ", ".join(agent_config.tools) if agent_config.tools else "-"
        typer.echo(
            f"{path.name}: name={agent_config.name} model={agent_config.model} tools=[{tools}]"
        )


@app.command("new-agent")
def new_agent(
    name: str = typer.Argument(..., help="エージェント名(表示用。ファイル名にも使用)"),
    system_prompt: str = typer.Option(..., "--system-prompt", help="システムプロンプト"),
    model: str = typer.Option("gpt-5.6-luna", "--model", help="使用するモデルID"),
    tools: list[str] = typer.Option(
        [], "--tool", help="使用するツール名(繰り返し指定可)。my-agents list-tools で確認できる"
    ),
    base_url: str = typer.Option(
        None, "--base-url", help="OpenAI互換の別APIエンドポイント(省略時はOpenAI公式API)"
    ),
    output: Path = typer.Option(None, "--output", help="出力先パス。省略時は agents/<name>.yaml"),
    force: bool = typer.Option(False, "--force", help="出力先が既に存在する場合に上書きする"),
) -> None:
    """新しいエージェント設定YAMLを生成する。"""
    unknown = [t for t in tools if t not in TOOL_REGISTRY]
    if unknown:
        available = ", ".join(sorted(TOOL_REGISTRY))
        typer.secho(
            f"エラー: 未知のツール名です: {unknown} (利用可能なツール: {available})",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    dest = output if output is not None else AGENTS_DIR / f"{name}.yaml"
    if dest.exists() and not force:
        typer.secho(
            f"エラー: {dest} は既に存在します。上書きするには --force を指定してください。",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    data = {
        "name": name,
        "model": model,
        "system_prompt": system_prompt,
        "tools": list(tools),
        "base_url": base_url,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    typer.echo(f"作成しました: {dest}")


@app.command()
def help(ctx: typer.Context) -> None:
    """コマンド一覧とヘルプを表示する。"""
    typer.echo(ctx.parent.get_help())


def main() -> None:
    raw = sys.argv[1:]
    if raw == ["--version"]:
        print(f"my-agents {tool_version()}")
        sys.exit(0)

    app()


if __name__ == "__main__":
    main()
