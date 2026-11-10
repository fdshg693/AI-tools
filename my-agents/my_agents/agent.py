"""YAML設定からエージェント(LangGraphのcompiled graph)を組み立てる。"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from .config import AgentConfig
from .run_log import write_run_log
from .skills import format_skills_catalog
from .tools import resolve_tools

# 実行時のカレントディレクトリに依存せず、常にこのパッケージが置かれた
# tools/my-agents/.env を参照する。
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def missing_required_key_message(key: str, env_path: Path) -> str:
    env_state = "未設定" if key not in os.environ else "空で設定されている"
    if not env_path.is_file():
        file_state = f"想定した .env は {env_path} ですが、ファイルがありません。"
    else:
        file_state = f"{env_path} はありますが、{key} が無いか空です。"
    return f"{key} が解決できません。\n環境変数 {key} は{env_state}です。\n{file_state}"


def build_chat_model(config: AgentConfig) -> ChatOpenAI:
    load_dotenv(ENV_PATH, override=False)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(missing_required_key_message("OPENAI_API_KEY", ENV_PATH))

    # base_url を設定すればOpenAI互換の別APIにも切り替えられる(未指定ならOpenAI公式APIを使用)。
    return ChatOpenAI(
        model=config.model,
        api_key=api_key,
        base_url=config.base_url,
        use_responses_api=True,
        output_version="responses/v1",
    )


def build_system_prompt(config: AgentConfig) -> str:
    """エージェントYAMLの system_prompt に、利用可能なスキル一覧を追記する。"""
    catalog = format_skills_catalog()
    if not catalog:
        return config.system_prompt
    return f"{config.system_prompt.rstrip()}\n\n{catalog}"


def build_agent(config: AgentConfig):
    model = build_chat_model(config)
    tools = resolve_tools(config.tools)
    return create_agent(model=model, tools=tools, system_prompt=build_system_prompt(config))


def run_agent(config: AgentConfig, prompt: str) -> tuple[str, Path]:
    """エージェントを実行し、(最終回答テキスト, 実行ログパス) を返す。"""
    started_at = datetime.now().astimezone()
    graph = build_agent(config)
    result = graph.invoke({"messages": [{"role": "user", "content": prompt}]})
    messages = result["messages"]
    # content は output_version="responses/v1" によりテキスト以外のブロックも
    # 含みうる list 形式のため、.text でプレーンテキストのみ取り出す。
    # .text は TextAccessor を返すことがあるため str() で正規化する。
    answer = str(messages[-1].text)
    log_path = write_run_log(
        agent_name=config.name,
        model=config.model,
        prompt=prompt,
        messages=messages,
        final_answer=answer,
        started_at=started_at,
    )
    return answer, log_path
