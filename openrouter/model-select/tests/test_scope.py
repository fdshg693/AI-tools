from model_select.scope import filter_in_scope

BASE_PRICING = {"prompt": "0.000001", "completion": "0.000002"}


def make_model(model_id: str, coding_index: float | None) -> dict:
    model = {"id": model_id, "pricing": dict(BASE_PRICING)}
    if coding_index is not None:
        model["benchmarks"] = {"artificial_analysis": {"coding_index": coding_index}}
    return model


def test_excludes_variant_ids():
    models = [make_model("anthropic/claude-sonnet-4.5:batch", 71.5)]
    assert filter_in_scope(models, minimum=50) == []


def test_excludes_models_missing_coding_index():
    models = [make_model("openai/gpt-5.5", None)]
    assert filter_in_scope(models, minimum=50) == []


def test_excludes_models_with_empty_benchmarks():
    model = make_model("openai/gpt-5.5", None)
    model["benchmarks"] = {}
    assert filter_in_scope([model], minimum=50) == []


def test_keeps_model_satisfying_both_conditions():
    models = [make_model("anthropic/claude-sonnet-5", 71.5)]
    assert filter_in_scope(models, minimum=50) == models


def test_excludes_models_below_minimum():
    models = [make_model("deepseek/deepseek-v4-pro", 49.9)]
    assert filter_in_scope(models, minimum=50) == []
