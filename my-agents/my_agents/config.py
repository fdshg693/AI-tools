"""エージェント定義YAMLの読み込み。"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """1エージェント分の設定(YAML 1ファイルに対応)。"""

    name: str
    model: str
    system_prompt: str
    tools: list[str] = Field(default_factory=list)
    base_url: str | None = None


def load_agent_config(path: str | Path) -> AgentConfig:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AgentConfig.model_validate(data)
