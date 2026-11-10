"""Onaの環境(コンテナ)を作成・起動し、その中でタスクを実行して停止するCLI（コマンド名: ona-run）。"""

import argparse
import json
import subprocess
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_PATH = SCRIPT_DIR / "logs" / "runs.jsonl"

DEFAULT_START_TIMEOUT = 300
DEFAULT_TASK_TIMEOUT = 1800
POLL_INTERVAL_SECONDS = 5

EXIT_INFRA_ERROR = 64

RUNNING_PHASE = "ENVIRONMENT_PHASE_RUNNING"
# 起動待ち中にこれらのphaseへ遷移したら、RUNNINGへ到達する見込みがないため即座にエラー終了する。
TERMINAL_FAILURE_PHASES = {
    "ENVIRONMENT_PHASE_STOPPING",
    "ENVIRONMENT_PHASE_STOPPED",
    "ENVIRONMENT_PHASE_DELETING",
    "ENVIRONMENT_PHASE_DELETED",
}

# `{task}` を実際のタスク文字列で置換して使う、コンテナ内実行コマンドの簡易テンプレート。
AGENT_TEMPLATES: dict[str, list[str]] = {
    "claude": ["claude", "-p", "{task}", "--dangerously-skip-permissions"],
    "codex": ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "{task}"],
}


class OnaRunError(Exception):
    """環境作成・起動待ちなど、インフラ操作の失敗を表す例外。"""


def tool_version() -> str:
    data = tomllib.loads((SCRIPT_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


def split_command_argv(argv: list[str]) -> tuple[list[str], list[str] | None]:
    """`--command`トークン以降を素朴な文字列一致で手動split する。

    argparseの`nargs=REMAINDER`は他のオプションとの位置関係によって挙動が不安定に
    なることがあるため使わない（同じ理由で`tools/interactive-cli-wrapper/icw_cli.py`の
    `start -- <対象コマンド...>`も手動splitを採用している）。戻り値は
    (argparseに渡す残りのargv, --command以降のトークン列。--command未指定ならNone)。
    """
    if "--command" not in argv:
        return argv, None
    idx = argv.index("--command")
    return argv[:idx], argv[idx + 1 :]


def resolve_template(agent: str | None, command: list[str] | None) -> list[str]:
    return command if command is not None else AGENT_TEMPLATES[agent]


def needs_task(template: list[str]) -> bool:
    return any("{task}" in token for token in template)


def build_exec_argv(template: list[str], task: str | None) -> list[str]:
    """コンテナ内で実行するコマンドのargvを組み立てる（`{task}`プレースホルダをtaskで置換）。"""
    if task is None:
        return list(template)
    return [token.replace("{task}", task) for token in template]


def read_task(task_arg: str | None) -> str:
    if task_arg is not None:
        return task_arg

    if sys.stdin.isatty():
        print(
            "エラー: タスクが指定されていません。"
            "位置引数で指定するか、標準入力から渡してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    task = sys.stdin.read().strip()
    if not task:
        print("エラー: 標準入力から読み込んだタスクが空です。", file=sys.stderr)
        sys.exit(1)
    return task


def run_ona(*args: str) -> subprocess.CompletedProcess:
    """`ona`サブコマンドを実行し、stdout/stderrを文字列としてキャプチャする薄いラッパー。"""
    return subprocess.run(["ona", *args], capture_output=True, text=True)


def resolve_default_class_id() -> str:
    result = run_ona("environment", "list-classes", "-o", "json")
    if result.returncode != 0:
        raise OnaRunError(f"環境クラス一覧の取得に失敗しました: {result.stderr.strip()}")

    classes = json.loads(result.stdout)
    if not classes:
        raise OnaRunError("利用可能な環境クラスが見つかりませんでした。")

    for item in classes:
        if item.get("default"):
            return item["id"]
    return classes[0]["id"]


def create_environment(repo_or_project: str, class_id: str | None) -> str:
    """`ona environment create --dont-wait`で環境を作成し、環境IDを返す。

    `--class-id`未指定でまず試し、失敗した場合のみ`list-classes`で解決した
    デフォルトクラスを付けて1回だけリトライする（Ona公式ドキュメント間で
    class-idの要否記述が食い違うための決め打ち回避）。
    """
    args = ["environment", "create", repo_or_project, "--dont-wait"]
    if class_id:
        args += ["--class-id", class_id]

    result = run_ona(*args)
    if result.returncode == 0:
        env_id = result.stdout.strip()
        if not env_id:
            raise OnaRunError("環境作成コマンドが環境IDを返しませんでした。")
        return env_id

    if class_id is None:
        default_class_id = resolve_default_class_id()
        return create_environment(repo_or_project, default_class_id)

    raise OnaRunError(f"環境の作成に失敗しました: {result.stderr.strip()}")


def wait_until_running(env_id: str, start_timeout: int) -> None:
    deadline = time.monotonic() + start_timeout
    while True:
        result = run_ona("environment", "get", env_id, "-o", "json")
        if result.returncode != 0:
            raise OnaRunError(f"環境状態の取得に失敗しました: {result.stderr.strip()}")

        envs = json.loads(result.stdout)
        if not envs:
            raise OnaRunError(f"環境が見つかりません: {env_id}")

        phase = envs[0].get("status", {}).get("phase")
        if phase == RUNNING_PHASE:
            return
        if phase in TERMINAL_FAILURE_PHASES:
            raise OnaRunError(f"環境が起動に失敗しました（phase={phase}）")
        if time.monotonic() >= deadline:
            raise OnaRunError(
                f"環境の起動待ちがタイムアウトしました（{start_timeout}秒、phase={phase}）"
            )
        time.sleep(POLL_INTERVAL_SECONDS)


def exec_task(env_id: str, task_argv: list[str], task_timeout: int) -> int:
    """`ona environment exec`でタスクを実行する。stdout/stderrは継承しそのまま表示する。"""
    result = subprocess.run(
        ["ona", "environment", "exec", env_id, "--timeout", str(task_timeout), "--", *task_argv]
    )
    return result.returncode


def cleanup_environment(env_id: str, mode: str) -> None:
    if mode == "keep":
        return

    action = "stop" if mode == "stop" else "delete"
    result = run_ona("environment", action, env_id)
    if result.returncode != 0:
        print(
            f"警告: 環境のクリーンアップ（{action}）に失敗しました: {result.stderr.strip()}",
            file=sys.stderr,
        )


def append_log(record: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ona-run",
        description="Onaの環境を作成/起動し、その中でタスクを実行して停止するCLI",
    )
    parser.add_argument("--version", action="version", version=f"ona-run {tool_version()}")
    parser.add_argument("repo_or_project", help="リポジトリURL、またはOnaプロジェクトID")
    parser.add_argument(
        "task",
        nargs="?",
        help="タスク内容（自然文プロンプト）。省略時は標準入力から読み込む",
    )
    parser.add_argument(
        "--agent",
        choices=sorted(AGENT_TEMPLATES),
        help="タスクコマンドの簡易テンプレート（--commandと同時指定不可、どちらか一方が必須）",
    )
    parser.epilog = (
        "--command TOKEN... : --agentの代わりに、コンテナ内で実行する完全なコマンドをargvの"
        "トークン列として指定する（トークン中の{task}はタスク文字列に置換される）。"
        "以降の全トークンをそのままコマンドとして扱うため、他のオプションより後ろ・末尾に置くこと。"
        "--agentと同時指定不可、どちらか一方が必須。"
    )
    parser.add_argument(
        "--cleanup",
        choices=["stop", "delete", "keep"],
        default="stop",
        help="タスク終了後の環境の扱い（既定: stop）",
    )
    parser.add_argument(
        "--class-id",
        help="環境クラスID（省略時はまずクラス指定なしで作成を試み、失敗時のみ既定クラスで自動リトライ）",
    )
    parser.add_argument(
        "--start-timeout",
        type=int,
        default=DEFAULT_START_TIMEOUT,
        help=f"環境がRUNNINGになるまでの待機タイムアウト秒（既定: {DEFAULT_START_TIMEOUT}）",
    )
    parser.add_argument(
        "--task-timeout",
        type=int,
        default=DEFAULT_TASK_TIMEOUT,
        help=f"タスク実行（ona environment exec）のタイムアウト秒（既定: {DEFAULT_TASK_TIMEOUT}）",
    )
    return parser


def main() -> None:
    parser_argv, command = split_command_argv(sys.argv[1:])
    parser = build_arg_parser()
    args = parser.parse_args(parser_argv)

    if (args.agent is None) == (command is None):
        parser.error("--agent か --command のどちらか一方を指定してください。")
    if command is not None and not command:
        parser.error("--command には実行するコマンドのトークンを1つ以上指定してください。")

    template = resolve_template(args.agent, command)
    task = read_task(args.task) if needs_task(template) else args.task
    task_argv = build_exec_argv(template, task)

    start = time.monotonic()
    env_id: str | None = None
    task_exit_code: int | None = None

    try:
        env_id = create_environment(args.repo_or_project, args.class_id)
        print(f"ona-run: environment created: {env_id}", file=sys.stderr)
        wait_until_running(env_id, args.start_timeout)

        task_exit_code = exec_task(env_id, task_argv, args.task_timeout)
        status = "success" if task_exit_code == 0 else "task_failed"
        print(f"ona-run: status={status}", file=sys.stderr)
    except OnaRunError as e:
        print(f"エラー: {e}", file=sys.stderr)
        print("ona-run: status=infra_error", file=sys.stderr)
        sys.exit(EXIT_INFRA_ERROR)
    except Exception as e:
        print(f"エラー: 予期しないエラーが発生しました: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if env_id:
            cleanup_environment(env_id, args.cleanup)
        append_log(
            {
                "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                "env_id": env_id,
                "repo": args.repo_or_project,
                "agent": args.agent,
                "exit_code": task_exit_code,
                "duration_seconds": round(time.monotonic() - start, 3),
            }
        )

    sys.exit(task_exit_code)


if __name__ == "__main__":
    main()
