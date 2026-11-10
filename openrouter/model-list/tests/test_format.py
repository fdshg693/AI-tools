import json

from model_list.format import (
    format_models_json,
    format_models_table,
    format_pareto_json,
    format_pareto_table,
    format_providers_json,
    format_providers_table,
)


def test_format_models_table_includes_header_and_rows():
    table = format_models_table(
        [
            {"id": "openai/gpt-5", "name": "GPT-5", "context_length": 128000},
            {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro", "context_length": 1000000},
        ]
    )
    lines = table.splitlines()
    assert lines[0].split() == ["id", "name", "context_length"]
    assert "openai/gpt-5" in table
    assert "GPT-5" in table
    assert "128000" in table
    assert "google/gemini-2.5-pro" in table


def test_format_models_table_empty_still_has_header():
    table = format_models_table([])
    lines = table.splitlines()
    assert lines[0].split() == ["id", "name", "context_length"]
    assert len(lines) == 2


def test_format_models_table_falls_back_name_and_blank_context():
    table = format_models_table([{"id": "x-ai/grok-4"}])
    assert "x-ai/grok-4" in table
    assert "None" not in table


def test_format_models_json_keeps_context_length_numeric():
    payload = json.loads(
        format_models_json([{"id": "openai/gpt-5", "name": "GPT-5", "context_length": 128000}])
    )
    assert payload == [{"id": "openai/gpt-5", "name": "GPT-5", "context_length": 128000}]


def test_format_models_json_empty_is_array():
    assert json.loads(format_models_json([])) == []


def test_format_providers_table_one_slug_per_line():
    assert format_providers_table(["google", "openai"]) == "google\nopenai"


def test_format_providers_table_empty_is_empty_string():
    assert format_providers_table([]) == ""


def test_format_providers_json():
    assert json.loads(format_providers_json(["google", "openai"])) == ["google", "openai"]


def test_format_pareto_table_sort_order_and_headers():
    table = format_pareto_table(
        [
            {
                "id": "openai/cheap",
                "name": "cheap",
                "coding_index": 50.5,
                "price_prompt_per_million": 1.2,
            },
            {
                "id": "openai/mid",
                "name": "mid",
                "coding_index": 71.5,
                "price_prompt_per_million": 3.0,
            },
        ],
        "price_prompt_per_million",
    )
    lines = table.splitlines()
    assert lines[0].split() == ["id", "name", "index", "price"]
    assert "50.5" in lines[2]
    assert "1.20" in lines[2]
    assert "71.5" in lines[3]
    assert "3.00" in lines[3]


def test_format_pareto_json_keeps_numeric_values():
    payload = json.loads(
        format_pareto_json(
            [
                {
                    "id": "openai/gpt-5",
                    "name": "GPT-5",
                    "coding_index": 71.5,
                    "price_prompt_per_million": 1.25,
                }
            ],
            "price_prompt_per_million",
        )
    )
    assert payload == [{"id": "openai/gpt-5", "name": "GPT-5", "index": 71.5, "price": 1.25}]
