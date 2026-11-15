"""エージェントから利用できるツールをコード内で定義するレジストリ。

各ツールは責務ごとに分けたモジュール(`time_tools.py`, `mslearn_tools.py`, ...)で
`@tool` 関数として定義し、ここで集約して `TOOL_REGISTRY` に登録する。
YAML設定ファイルはこのレジストリのキー(ツール名)を参照するだけでよい。

新しいツールを追加する場合:
1. このパッケージ内に新規モジュール(または既存モジュール)に `@tool` 関数を実装する
2. 下の `_TOOLS` にインポートを足す

`load_skill` は全エージェントに自動付与される(YAMLの `tools:` に書かなくても使える)。
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from .mslearn_tools import mslearn_code_search, mslearn_fetch, mslearn_search
from .skill_tools import load_skill
from .tavily_tools import tavily_extract, tavily_search
from .time_tools import get_time

# 全エージェントに常に付与するツール(YAMLの tools: に無くても resolve_tools が足す)。
ALWAYS_ON_TOOLS: tuple[BaseTool, ...] = (load_skill,)

_TOOLS: list[BaseTool] = [
    get_time,
    mslearn_search,
    mslearn_code_search,
    mslearn_fetch,
    tavily_search,
    tavily_extract,
    load_skill,
]

TOOL_REGISTRY: dict[str, BaseTool] = {t.name: t for t in _TOOLS}


def resolve_tools(names: list[str]) -> list[BaseTool]:
    """ツール名のリストを、対応するツールオブジェクトのリストに解決する。

    ALWAYS_ON_TOOLS は names に含まれていなくても末尾に付与する(重複は除く)。
    """
    unknown = [name for name in names if name not in TOOL_REGISTRY]
    if unknown:
        available = ", ".join(sorted(TOOL_REGISTRY))
        raise ValueError(f"未知のツール名です: {unknown} (利用可能なツール: {available})")
    tools = [TOOL_REGISTRY[name] for name in names]
    present = {t.name for t in tools}
    for tool in ALWAYS_ON_TOOLS:
        if tool.name not in present:
            tools.append(tool)
    return tools
