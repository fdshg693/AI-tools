"""価格算出: ベース値と``pricing.overrides[]``内の最大値（安全側=最悪ケース）。"""

from __future__ import annotations

TOKENS_PER_MILLION = 1_000_000


def worst_case_price_per_token(model: dict, field: str) -> float:
    """モデルの``field``（``"prompt"``または``"completion"``）について、
    ``pricing``のベース値と``pricing.overrides[]``内の同フィールドの最大値を返す（$/token）。

    ``overrides``の各要素は閾値条件（``min_prompt_tokens``等）を持つが、その判定は行わず
    フィールドが存在する要素は常に比較対象に含める。フィールドが無い要素はスキップする。
    """
    pricing = model["pricing"]
    values = [float(pricing[field])]
    for override in pricing.get("overrides", []):
        if field in override:
            values.append(float(override[field]))
    return max(values)


def per_million_tokens(price_per_token: float) -> float:
    """$/token を $/M tokens に変換する。"""
    return price_per_token * TOKENS_PER_MILLION
