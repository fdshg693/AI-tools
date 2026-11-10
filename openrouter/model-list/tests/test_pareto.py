from model_list.pareto import (
    CACHE_FLOOR,
    DEFAULT_MIN_INDEX,
    DEFAULT_PROVIDERS,
    PRICE_KEYS,
    build_record,
    filter_pareto_frontier,
    parse_provider_option,
    records_from_models,
    select_pareto,
    unknown_providers,
)

BASE_PRICING = {"prompt": "0.000001", "completion": "0.000002"}
PROMPT_KEY = PRICE_KEYS["prompt"]
COMPLETION_KEY = PRICE_KEYS["completion"]


def make_model(
    model_id: str,
    coding_index: float | None,
    *,
    prompt: str = "0.000001",
    completion: str = "0.000002",
    name: str | None = None,
) -> dict:
    model = {
        "id": model_id,
        "pricing": {"prompt": prompt, "completion": completion},
    }
    if name is not None:
        model["name"] = name
    if coding_index is not None:
        model["benchmarks"] = {"artificial_analysis": {"coding_index": coding_index}}
    return model


def make_record(
    model_id: str,
    coding_index: float,
    *,
    prompt: float,
    completion: float | None = None,
) -> dict:
    built = build_record(
        make_model(
            model_id,
            coding_index,
            prompt=str(prompt / 1_000_000),
            completion=str((prompt if completion is None else completion) / 1_000_000),
        )
    )
    assert built is not None
    return built


def test_records_from_models_excludes_variants_and_low_index():
    models = [
        make_model("anthropic/claude-sonnet-4.5:batch", 71.5),
        make_model("openai/gpt-5.5", None),
        make_model("deepseek/deepseek-v4-pro", 19.9),
        make_model("google/gemini-2.5-pro", 60, name="Gemini 2.5 Pro"),
    ]
    records = records_from_models(models)
    assert [record["id"] for record in records] == ["google/gemini-2.5-pro"]
    assert records[0]["provider"] == "google"
    assert records[0]["name"] == "Gemini 2.5 Pro"
    assert records[0]["coding_index"] == 60


def test_cache_floor_keeps_index_20():
    models = [make_model("openai/gpt-oss", 20)]
    assert records_from_models(models, minimum=CACHE_FLOOR)[0]["id"] == "openai/gpt-oss"


def test_filter_pareto_frontier_drops_dominated():
    cheap_low = make_record("openai/a", 50, prompt=1.0)
    mid = make_record("openai/b", 60, prompt=1.5)
    expensive_mid = make_record("openai/c", 55, prompt=3.0)
    expensive_high = make_record("openai/d", 70, prompt=3.0)
    frontier = filter_pareto_frontier([cheap_low, mid, expensive_mid, expensive_high], PROMPT_KEY)
    assert {record["id"] for record in frontier} == {"openai/a", "openai/b", "openai/d"}


def test_equal_price_and_index_both_remain():
    left = make_record("openai/a", 50, prompt=1.0)
    right = make_record("anthropic/b", 50, prompt=1.0)
    frontier = filter_pareto_frontier([left, right], PROMPT_KEY)
    assert {record["id"] for record in frontier} == {"openai/a", "anthropic/b"}


def test_select_pareto_filters_then_frontiers_and_sorts_by_price():
    records = [
        make_record("openai/cheap", 50, prompt=1.0),
        make_record("openai/mid", 60, prompt=2.0),
        make_record("google/other", 80, prompt=0.5),
        make_record("openai/dominated", 55, prompt=3.0),
        make_record("openai/low", 40, prompt=0.1),
    ]
    rows = select_pareto(
        records, providers=["openai"], min_index=DEFAULT_MIN_INDEX, price_key=PROMPT_KEY
    )
    assert [record["id"] for record in rows] == ["openai/cheap", "openai/mid"]
    prices = [record[PROMPT_KEY] for record in rows]
    indexes = [record["coding_index"] for record in rows]
    assert prices == sorted(prices)
    assert indexes == sorted(indexes)


def test_select_pareto_completion_axis():
    records = [
        make_record("openai/a", 50, prompt=9.0, completion=1.0),
        make_record("openai/b", 70, prompt=1.0, completion=2.0),
        make_record("openai/c", 55, prompt=2.0, completion=3.0),
    ]
    rows = select_pareto(records, providers=None, min_index=50, price_key=COMPLETION_KEY)
    assert [record["id"] for record in rows] == ["openai/a", "openai/b"]


def test_parse_provider_option_splits_and_strips():
    assert parse_provider_option("openai, anthropic") == ["openai", "anthropic"]
    assert parse_provider_option("  ") is None
    assert parse_provider_option(None) is None


def test_unknown_providers_preserves_order():
    assert unknown_providers(["openai", "alibaba", "openai", "mistral"]) == ["alibaba", "mistral"]


def test_qwen_is_a_supported_provider():
    assert "qwen" in DEFAULT_PROVIDERS
    assert unknown_providers(["qwen"]) == []
