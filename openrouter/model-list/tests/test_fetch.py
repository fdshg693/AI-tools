from model_list.fetch import (
    CATALOG_LIMIT,
    DEFAULT_LIMIT,
    DEFAULT_SORT,
    NEWEST_SORT,
    apply_id_search,
    author_from_model_id,
    catalog_query_params,
    filter_by_id,
    models_query_params,
    pareto_query_params,
    sort_by_newest,
    unique_authors,
)


def test_models_query_params_default():
    assert models_query_params() == {"sort": DEFAULT_SORT, "limit": DEFAULT_LIMIT}


def test_models_query_params_includes_model_authors():
    assert models_query_params(limit=20, model_authors="openai") == {
        "sort": DEFAULT_SORT,
        "limit": 20,
        "model_authors": "openai",
    }


def test_models_query_params_omits_empty_model_authors():
    assert "model_authors" not in models_query_params(model_authors=None)
    assert "model_authors" not in models_query_params(model_authors="")


def test_models_query_params_newest_sort():
    assert models_query_params(limit=CATALOG_LIMIT, sort=NEWEST_SORT) == {
        "sort": NEWEST_SORT,
        "limit": CATALOG_LIMIT,
    }


def test_catalog_query_params_uses_limit_1000():
    assert catalog_query_params() == {"limit": CATALOG_LIMIT}


def test_author_from_model_id_strips_tilde():
    assert author_from_model_id("~openai/gpt-latest") == "openai"
    assert author_from_model_id("google/gemini-2.5-pro") == "google"


def test_unique_authors_dedupes_sorts_and_strips_tilde():
    models = [
        {"id": "qwen/qwen3-coder"},
        {"id": "~openai/gpt-latest"},
        {"id": "openai/gpt-5"},
        {"id": "google/gemini-2.5-pro"},
        {"id": ""},
        {},
    ]
    assert unique_authors(models) == ["google", "openai", "qwen"]


def test_filter_by_id_is_case_insensitive_substring_on_id_only():
    models = [
        {"id": "openai/gpt-5", "name": "GPT-5"},
        {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
        {"id": "anthropic/claude-sonnet-4.6", "name": "mentions gpt in name only"},
        {"id": "~openai/gpt-latest"},
    ]
    matched = filter_by_id(models, "GPT-5")
    assert [model["id"] for model in matched] == ["openai/gpt-5"]
    matched_gpt = filter_by_id(models, "gpt")
    assert [model["id"] for model in matched_gpt] == [
        "openai/gpt-5",
        "~openai/gpt-latest",
    ]
    matched_openai = filter_by_id(models, "openai/")
    assert [model["id"] for model in matched_openai] == [
        "openai/gpt-5",
        "~openai/gpt-latest",
    ]


def test_filter_by_id_blank_query_keeps_all():
    models = [{"id": "openai/gpt-5"}, {"id": "google/gemini-2.5-pro"}]
    assert filter_by_id(models, "  ") == models


def test_sort_by_newest_puts_missing_created_last():
    models = [
        {"id": "old", "created": 100},
        {"id": "no-created"},
        {"id": "new", "created": 300},
        {"id": "mid", "created": 200},
    ]
    assert [model["id"] for model in sort_by_newest(models)] == [
        "new",
        "mid",
        "old",
        "no-created",
    ]


def test_pareto_query_params_omits_sort_and_limit():
    assert pareto_query_params(model_authors="openai,anthropic", min_coding_index=20) == {
        "model_authors": "openai,anthropic",
        "min_coding_index": 20,
    }


def test_apply_id_search_newest_then_limit():
    models = [
        {"id": "openai/gpt-4o", "created": 100},
        {"id": "openai/gpt-5", "created": 300},
        {"id": "google/gemini-2.5-pro", "created": 400},
        {"id": "openai/gpt-5.6-luna", "created": 200},
    ]
    result = apply_id_search(models, "gpt-", limit=2)
    assert [model["id"] for model in result] == ["openai/gpt-5", "openai/gpt-5.6-luna"]
