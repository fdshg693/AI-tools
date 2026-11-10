"""Multi-agent orchestrator on the Cursor Python SDK.

Phase 1 (planner): takes the user goal and registers the subagents needed to
accomplish it through custom tools (``register_subagent`` / ``set_handoff_prompt``).
Registration happens via tool execution rather than free-text parsing, so the
subagent definitions are schema-validated and robust.

Phase 2 (executor): a fresh agent is created with the registered subagents
attached as inline ``AgentDefinition`` and sent the handoff prompt. The executor
spawns the subagents via the ``Agent`` tool as described in the handoff plan.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cursor_sdk import (
    Agent,
    AgentDefinition,
    AgentOptions,
    CustomTool,
    CustomToolContext,
    Cursor,
    CursorClient,
    LocalAgentOptions,
    ModelSelection,
)


REQUESTED_MODEL = "grok-4.5-medium"
MODEL_ALIASES = {
    # Cursor renamed the Grok 4.5 slugs in July 2026.
    "grok-4.5-medium": "cursor-grok-4.5-medium",
}
DEFAULT_PROMPT = (
    "このリポジトリの目的を1文で説明し、その説明を補強するための小さな"
    "サンプルコードを1つ示してください。"
)
BRIDGE_READY_PREFIX = "cursor-sdk-bridge ready "
ENV_PATH = Path(__file__).resolve().parent / ".env"


def missing_required_key_message(key: str, env_path: Path) -> str:
    env_state = "未設定" if key not in os.environ else "空で設定されている"
    if not env_path.is_file():
        file_state = f"想定した .env は {env_path} ですが、ファイルがありません。"
    else:
        file_state = f"{env_path} はありますが、{key} が無いか空です。"
    return f"{key} が解決できません。\n環境変数 {key} は{env_state}です。\n{file_state}"


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries without overriding process environment."""

    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue

        key, value = (part.strip() for part in line.split("=", 1))
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value


def start_bridge(workspace: Path) -> tuple[CursorClient, subprocess.Popen[str]]:
    """Start the SDK bridge and connect without exposing its auth token."""

    process = subprocess.Popen(
        ["cursor-sdk-bridge", "--workspace", str(workspace)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        if process.stderr is None:
            raise RuntimeError("cursor-sdk-bridge の標準エラー出力を開けません。")

        line = process.stderr.readline()
        if not line.startswith(BRIDGE_READY_PREFIX):
            raise RuntimeError(f"cursor-sdk-bridge が起動できませんでした。 {line.strip()}")

        discovery: dict[str, Any] = json.loads(line.removeprefix(BRIDGE_READY_PREFIX))
        token_file = discovery.get("authTokenFile")
        if not token_file:
            raise RuntimeError("SDKブリッジの認証情報が見つかりません。")

        token = Path(token_file).read_text(encoding="utf-8").strip()
        client = CursorClient.connect(
            base_url=discovery["url"],
            auth_token=token,
        )
        return client, process
    except Exception:
        stop_bridge(process)
        raise


def stop_bridge(process: subprocess.Popen[str]) -> None:
    """Terminate the bridge process started by this script."""

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if process.stderr is not None:
        process.stderr.close()


def resolve_model(client: CursorClient, api_key: str, requested: str) -> str | ModelSelection:
    """Resolve a requested model ID and its current parameterized variant."""

    models = Cursor.models.list(client=client, api_key=api_key)
    available = {model.id for model in models}
    if requested in available:
        return requested

    alias = MODEL_ALIASES.get(requested)
    if alias in available:
        return alias

    if requested == "grok-4.5-medium":
        grok_model = next((model for model in models if model.id == "grok-4.5"), None)
        if grok_model is not None:
            for variant in grok_model.variants:
                params = {(param.id, param.value) for param in variant.params}
                if {("effort", "medium"), ("fast", "false")} <= params:
                    return ModelSelection(id=grok_model.id, params=variant.params)

    grok_models = sorted(model for model in available if "grok-4.5" in model)
    available_text = ", ".join(grok_models) or "なし"
    raise RuntimeError(
        f"モデル {requested!r} は利用できません。利用可能なGrok 4.5: {available_text}"
    )


@dataclass
class SubagentSpec:
    """A subagent definition registered by the planner."""

    name: str
    description: str
    prompt: str
    model: str = "inherit"


@dataclass
class PlannerRegistry:
    """Mutable state populated by the planner's custom tools.

    The planner calls ``register_subagent`` / ``set_handoff_prompt`` during its
    run; the orchestrator reads the results after the run finishes. This is the
    "register via tool execution, then read" pattern so we never parse the
    model's free-text output.
    """

    available_models: list[str] = field(default_factory=list)
    subagents: list[SubagentSpec] = field(default_factory=list)
    handoff_prompt: str | None = None

    def register_subagent(self, args: dict[str, Any], context: CustomToolContext) -> str:
        name = str(args["name"]).strip()
        if not name or any(ch.isspace() for ch in name):
            raise ValueError(f"subagent 名に空白を含めることはできません (got {name!r})")
        if any(spec.name == name for spec in self.subagents):
            raise ValueError(f"subagent 名 {name!r} は既に登録されています")

        model = str(args.get("model") or "inherit").strip()
        if model != "inherit" and model not in self.available_models:
            raise ValueError(
                f"モデル {model!r} は利用可能ではありません。"
                f" 利用可能: {', '.join(self.available_models) or 'なし'}"
                f"（親と同じにする場合は 'inherit' を指定してください）"
            )

        spec = SubagentSpec(
            name=name,
            description=str(args["description"]).strip(),
            prompt=str(args["prompt"]).strip(),
            model=model,
        )
        self.subagents.append(spec)
        return (
            f"サブエージェント {name!r} を登録しました"
            f"（model={model}, description={spec.description[:60]}...）"
        )

    def set_handoff_prompt(self, args: dict[str, Any], context: CustomToolContext) -> str:
        prompt = str(args["prompt"]).strip()
        if not prompt:
            raise ValueError("引き継ぎプロンプトが空です")
        self.handoff_prompt = prompt
        return (
            "引き継ぎプロンプトを設定しました。"
            " 全サブエージェントの登録が完了していれば終了してください。"
        )


PLANNER_INSTRUCTIONS = """\
あなたはタスクプランナーです。ユーザーの目標を達成するために、どのようなサブエージェントを何個用意すべきかを計画し、実行の流れを設計します。

以下の手順に従ってください。

1. ユーザーの目標を分析し、タスクを完遂するために必要な役割（サブエージェント）を特定する。タスクを1人のエージェントでこなせるほど単純なら、サブエージェントを1つだけ登録してもよい。

2. それぞれのサブエージェントについて register_subagent ツールを呼び出して登録する。各サブエージェントには以下を指定する:
   - name: 識別子。英数字・ハイフン・アンダースコアのみ。空白不可。
   - description: 親（実行エージェント）が「いつこのサブエージェントを起動すべきか」を判断するための短い説明。広すぎず狭すぎず、具体的に。
   - prompt: サブエージェントのシステムプロンプト。役割・制約・期待する出力形式を明示する。
   - model: "inherit"（実行エージェントと同じモデル）または利用可能なモデルIDのいずれか。

3. 全サブエージェントを登録し終えたら、set_handoff_prompt ツールを呼び出して実行エージェントへの引き継ぎプロンプトを設定する。このプロンプトは以下を含むこと:
   - ユーザーの元の目標
   - 登録したサブエージェントをどの順序・方法で起動してタスクを完了するかの実行計画
   - 最終的な成果物の要件

4. ツール呼び出しがすべて完了したら、登録したサブエージェントの一覧を短くまとめて終了する。

利用可能なモデルID: {models}
"""


def build_planner_tools(registry: PlannerRegistry) -> dict[str, CustomTool]:
    """Build the custom tools the planner uses to register subagents."""

    return {
        "register_subagent": CustomTool(
            description=(
                "タスク実行に必要なサブエージェントを登録する。"
                " 計画した各役割について1回ずつ呼び出す。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "サブエージェントの識別子。英数字・ハイフン・アンダースコアのみ。空白不可。",
                    },
                    "description": {
                        "type": "string",
                        "description": "親がこのサブエージェントをいつ起動すべきかを判断するための短い説明。",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "サブエージェントのシステムプロンプト。役割・制約・出力形式を明示する。",
                    },
                    "model": {
                        "type": "string",
                        "description": (
                            "サブエージェントが使うモデル。'inherit'（実行エージェントと同じ）"
                            " または利用可能なモデルID。"
                        ),
                        "default": "inherit",
                    },
                },
                "required": ["name", "description", "prompt"],
            },
            execute=registry.register_subagent,
        ),
        "set_handoff_prompt": CustomTool(
            description=(
                "実行エージェントへの引き継ぎプロンプトを設定する。"
                " 全サブエージェントの登録を終えた後に1回だけ呼び出す。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "ユーザーの元の目標と、サブエージェントをどう使ってタスクを"
                            " 完了するかの実行計画を含む引き継ぎプロンプト。"
                        ),
                    },
                },
                "required": ["prompt"],
            },
            execute=registry.set_handoff_prompt,
        ),
    }


def run_planner(
    client: CursorClient,
    api_key: str,
    model: str | ModelSelection,
    workspace: Path,
    user_input: str,
    available_models: list[str],
) -> PlannerRegistry:
    """Phase 1: planner registers subagents and a handoff prompt via tools."""

    registry = PlannerRegistry(available_models=available_models)
    instructions = PLANNER_INSTRUCTIONS.format(models=", ".join(available_models) or "なし")
    prompt = f"[プランナー指示]\n{instructions}\n\n[ユーザーの目標]\n{user_input}"

    with Agent.create(
        model=model,
        api_key=api_key,
        local=LocalAgentOptions(
            cwd=str(workspace),
            custom_tools=build_planner_tools(registry),
        ),
        client=client,
    ) as agent:
        result = agent.send(prompt).wait()

    if result.status != "finished":
        raise RuntimeError(
            f"Planner run failed: status={result.status}, error={getattr(result, 'error', None)}"
        )

    print("[planner] 出力:")
    print(result.result)
    print(f"[planner] 登録されたサブエージェント: {len(registry.subagents)}件")
    for spec in registry.subagents:
        print(f"  - {spec.name} (model={spec.model}): {spec.description}")
    if registry.handoff_prompt is None:
        raise RuntimeError(
            "プランナーが set_handoff_prompt を呼び出しませんでした。"
            " 目標が複雑すぎるか、モデルがツールを使えない可能性があります。"
        )
    return registry


def run_executor(
    client: CursorClient,
    api_key: str,
    model: str | ModelSelection,
    workspace: Path,
    registry: PlannerRegistry,
) -> str:
    """Phase 2: fresh executor agent runs the handoff plan with subagents."""

    agents: dict[str, AgentDefinition] = {
        spec.name: AgentDefinition(
            description=spec.description,
            prompt=spec.prompt,
            model=spec.model if spec.model != "inherit" else "inherit",
        )
        for spec in registry.subagents
    }

    with Agent.create(
        AgentOptions(
            model=model,
            api_key=api_key,
            local=LocalAgentOptions(cwd=str(workspace)),
            agents=agents,
        ),
        client=client,
    ) as agent:
        result = agent.send(registry.handoff_prompt).wait()

    if result.status != "finished":
        raise RuntimeError(
            f"Executor run failed: status={result.status}, error={getattr(result, 'error', None)}"
        )
    return result.result


def main() -> int:
    load_dotenv(ENV_PATH)

    parser = argparse.ArgumentParser(
        description="Cursor SDK による2フェーズのマルチエージェント実行"
    )
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT)
    parser.add_argument(
        "--model",
        default=os.environ.get("CURSOR_MODEL", REQUESTED_MODEL),
        help=f"モデルID（既定: {REQUESTED_MODEL}）",
    )
    args = parser.parse_args()

    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        raise RuntimeError(missing_required_key_message("CURSOR_API_KEY", ENV_PATH))

    workspace = Path(__file__).resolve().parents[2]
    client, bridge = start_bridge(workspace)
    try:
        model = resolve_model(client, api_key, args.model)
        available_models = [m.id for m in Cursor.models.list(client=client, api_key=api_key)]

        print("[phase 1] プランナーエージェントを実行します...")
        registry = run_planner(client, api_key, model, workspace, args.prompt, available_models)

        print("\n[phase 2] 実行エージェントをサブエージェント付きで実行します...")
        final = run_executor(client, api_key, model, workspace, registry)

        print("\n[executor] 最終出力:")
        print(final)
        return 0
    finally:
        client.close()
        stop_bridge(bridge)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        raise SystemExit(f"エラー: {error}") from error
