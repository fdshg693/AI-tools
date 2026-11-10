from model_select.cli import _build_record

BASE_PRICING = {"prompt": "0.000001", "completion": "0.000002"}


def test_build_record_extracts_provider_from_id():
    model = {
        "id": "openai/gpt-5.5",
        "name": "GPT-5.5",
        "pricing": dict(BASE_PRICING),
        "benchmarks": {"artificial_analysis": {"coding_index": 71.5}},
    }
    record = _build_record(model)
    assert record["provider"] == "openai"
    assert record["id"] == "openai/gpt-5.5"
    assert record["coding_index"] == 71.5


def test_build_record_keeps_hyphenated_provider_slug():
    model = {
        "id": "z-ai/glm-5",
        "pricing": dict(BASE_PRICING),
        "benchmarks": {"artificial_analysis": {"coding_index": 60}},
    }
    assert _build_record(model)["provider"] == "z-ai"
