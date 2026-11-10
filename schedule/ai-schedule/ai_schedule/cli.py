"""設定ファイル(YAML)をもとにWindowsタスクスケジューラを同期するCLI(Typer)。"""

from __future__ import annotations

from pathlib import Path

import typer

from .config import load_config
from .windows_task import create_or_update_task, delete_task, list_registered_names

app = typer.Typer(
    name="ai-schedule",
    help="設定ファイル(YAML)をもとに、登録済みPowerShellスクリプトの定期実行をWindowsタスクスケジューラへ同期するCLI",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def sync(
    config: Path = typer.Argument(..., help="スケジュール設定YAMLのパス"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="実際には変更せず、実行予定の操作のみ表示する"
    ),
) -> None:
    """設定ファイルの内容にWindowsタスクスケジューラを同期する(有効なジョブを作成/更新し、それ以外を削除)。"""
    try:
        schedule_config = load_config(config)
        existing = set(list_registered_names())
    except Exception as exc:  # noqa: BLE001 - CLIとしてエラー内容をそのまま伝える
        typer.secho(f"エラー: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    desired = {job.name: job for job in schedule_config.jobs if job.enabled}
    to_delete = sorted(existing - desired.keys())

    for job in desired.values():
        action = "更新" if job.name in existing else "作成"
        if dry_run:
            typer.echo(f"[dry-run] {action}: {job.name}")
            continue
        try:
            create_or_update_task(job)
            typer.echo(f"{action}: {job.name}")
        except Exception as exc:  # noqa: BLE001
            typer.secho(f"エラー ({job.name}): {exc}", fg=typer.colors.RED, err=True)

    for name in to_delete:
        if dry_run:
            typer.echo(f"[dry-run] 削除: {name}")
            continue
        try:
            delete_task(name)
            typer.echo(f"削除: {name}")
        except Exception as exc:  # noqa: BLE001
            typer.secho(f"エラー ({name}): {exc}", fg=typer.colors.RED, err=True)

    if not desired and not to_delete:
        typer.echo("変更はありません")


@app.command("list")
def list_jobs(
    config: Path = typer.Argument(..., help="スケジュール設定YAMLのパス"),
) -> None:
    """設定ファイルのジョブ一覧と、タスクスケジューラへの現在の登録状況を表示する。"""
    try:
        schedule_config = load_config(config)
        existing = set(list_registered_names())
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"エラー: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if not schedule_config.jobs:
        typer.echo("設定ファイルにジョブがありません")

    for job in schedule_config.jobs:
        state = "有効" if job.enabled else "無効"
        registered = "登録済み" if job.name in existing else "未登録"
        typer.echo(f"{job.name}: {state} / {registered} / schedule={job.schedule.type}")

    orphans = sorted(existing - {job.name for job in schedule_config.jobs})
    for name in orphans:
        typer.echo(f"{name}: 設定なし / 登録済み (sync実行で削除されます)")


@app.command()
def help(ctx: typer.Context) -> None:
    """コマンド一覧とヘルプを表示する。"""
    typer.echo(ctx.parent.get_help())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
