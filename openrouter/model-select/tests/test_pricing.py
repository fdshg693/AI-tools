from model_select.pricing import per_million_tokens, worst_case_price_per_token


def test_no_overrides_returns_base_value():
    model = {"pricing": {"prompt": "0.000002", "completion": "0.00001"}}
    assert worst_case_price_per_token(model, "prompt") == 0.000002
    assert worst_case_price_per_token(model, "completion") == 0.00001


def test_overrides_present_returns_max_of_base_and_overrides():
    model = {
        "pricing": {
            "prompt": "0.000002",
            "completion": "0.00001",
            "overrides": [
                {"min_prompt_tokens": 272000, "prompt": "0.000004", "completion": "0.000015"}
            ],
        }
    }
    assert worst_case_price_per_token(model, "prompt") == 0.000004
    assert worst_case_price_per_token(model, "completion") == 0.000015


def test_override_element_missing_field_is_skipped():
    model = {
        "pricing": {
            "prompt": "0.00000125",
            "completion": "0.00001",
            "overrides": [
                {
                    "min_prompt_tokens": 200000,
                    "prompt": "0.0000025",
                    "input_cache_read": "0.00000025",
                }
            ],
        }
    }
    # completion is absent from the override element, so the base value wins.
    assert worst_case_price_per_token(model, "completion") == 0.00001
    assert worst_case_price_per_token(model, "prompt") == 0.0000025


def test_base_value_wins_when_higher_than_overrides():
    model = {
        "pricing": {
            "prompt": "0.00001",
            "completion": "0.00001",
            "overrides": [{"prompt": "0.000004"}],
        }
    }
    assert worst_case_price_per_token(model, "prompt") == 0.00001


def test_per_million_tokens_conversion():
    assert per_million_tokens(0.000002) == 2.0
