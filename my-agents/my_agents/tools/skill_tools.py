"""スキル本文を取得するツール。"""

from __future__ import annotations

from langchain_core.tools import tool

from ..skills import load_skill_body


@tool
def load_skill(name: str) -> str:
    """スキル名に対応する SKILL.md の本文(フロントマター除く)をテキストで返す。

    利用可能なスキル名と description はシステムプロンプトの Available skills を参照。
    """
    return load_skill_body(name)
