"""coding_index と価格の 2 軸 Pareto 最適。bucket 分けはしない。"""

from __future__ import annotations

from collections.abc import Sequence

from model_list.fetch import author_from_model_id
from model_list.pricing import per_million_tokens, worst_case_price_per_token

DEFAULT_PROVIDERS = (
    "openai",
    "anthropic",
    "google",
    "qwen",
    "z-ai",
    "minimax",
    "x-ai",
    "moonshotai",
    "deepseek",
)
DEFAULT_MIN_INDEX = 50
CACHE_FLOOR = 20
PRICE_KEYS = {
    "prompt": "price_prompt_per_million",
    "completion": "price_completion_per_million",
}


def is_variant(model: dict) -> bool:
    """``:free``/`:batch`/`:thinking`等の variant id かどうか。"""
    return ":" in model["id"]


def has_coding_index(model: dict) -> bool:
    benchmarks = model.get("benchmarks")
    if not benchmarks:
        return False
    artificial_analysis = benchmarks.get("artificial_analysis")
    if not artificial_analysis:
        return False
    return artificial_analysis.get("coding_index") is not None


def in_scope(model: dict, minimum: float) -> bool:
    return (
        not is_variant(model)
        and has_coding_index(model)
        and model["benchmarks"]["artificial_analysis"]["coding_index"] >= minimum
    )


def build_record(model: dict) -> dict | None:
    """比較用レコード。価格が取れないモデルは ``None``。"""
    try:
        prompt = per_million_tokens(worst_case_price_per_token(model, "prompt"))
        completion = per_million_tokens(worst_case_price_per_token(model, "completion"))
        coding_index = float(model["benchmarks"]["artificial_analysis"]["coding_index"])
    except (KeyError, TypeError, ValueError):
        return None
    model_id = model["id"]
    return {
        "id": model_id,
        "name": model.get("name", model_id),
        "provider": author_from_model_id(model_id),
        "coding_index": coding_index,
        "price_prompt_per_million": prompt,
        "price_completion_per_million": completion,
    }


def records_from_models(models: list[dict], *, minimum: float = CACHE_FLOOR) -> list[dict]:
    records: list[dict] = []
    for model in models:
        if not in_scope(model, minimum):
            continue
        record = build_record(model)
        if record is not None:
            records.append(record)
    return records


def parse_provider_option(value: str | None) -> list[str] | None:
    if value is None:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return parts or None


def unknown_providers(providers: Sequence[str]) -> list[str]:
    allowed = set(DEFAULT_PROVIDERS)
    seen: set[str] = set()
    unknown: list[str] = []
    for provider in providers:
        if provider not in allowed and provider not in seen:
            seen.add(provider)
            unknown.append(provider)
    return unknown


def filter_records(
    records: list[dict],
    *,
    providers: Sequence[str] | None,
    min_index: float,
) -> list[dict]:
    allowed = set(providers) if providers is not None else None
    filtered: list[dict] = []
    for record in records:
        if record["coding_index"] < min_index:
            continue
        if allowed is not None and record["provider"] not in allowed:
            continue
        filtered.append(record)
    return filtered


def filter_pareto_frontier(items: list[dict], price_key: str) -> list[dict]:
    """価格が安く coding_index が高い側が優位。どちらも劣らない同士は残す。"""
    result: list[dict] = []
    for candidate in items:
        candidate_price = candidate[price_key]
        candidate_metric = candidate["coding_index"]
        dominated = False
        for other in items:
            if other is candidate:
                continue
            other_price = other[price_key]
            other_metric = other["coding_index"]
            not_worse = other_price <= candidate_price and other_metric >= candidate_metric
            strictly_better = other_price < candidate_price or other_metric > candidate_metric
            if not_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            result.append(candidate)
    return result


def sort_by_price(records: list[dict], price_key: str) -> list[dict]:
    return sorted(records, key=lambda record: (record[price_key], record["id"]))


def select_pareto(
    records: list[dict],
    *,
    providers: Sequence[str] | None,
    min_index: float,
    price_key: str,
) -> list[dict]:
    filtered = filter_records(records, providers=providers, min_index=min_index)
    return sort_by_price(filter_pareto_frontier(filtered, price_key), price_key)
