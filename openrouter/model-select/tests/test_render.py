from datetime import datetime, timezone

from model_select.render import render_report

SAMPLE_RECORDS = [
    {
        "id": "openai/gpt-5.5",
        "name": "GPT-5.5",
        "provider": "openai",
        "coding_index": 71.5,
        "price_prompt_per_million": 1.25,
        "price_completion_per_million": 10.0,
    },
    {
        "id": "anthropic/claude-sonnet-5",
        "name": "Claude Sonnet 5",
        "provider": "anthropic",
        "coding_index": 70.0,
        "price_prompt_per_million": 3.0,
        "price_completion_per_million": 15.0,
    },
]


def test_render_report_embeds_provider_and_filter_ui():
    html = render_report(datetime(2026, 9, 7, tzinfo=timezone.utc), SAMPLE_RECORDS, floor=50)
    assert 'id="provider-filters"' in html
    assert 'id="providers-all"' in html
    assert 'id="providers-none"' in html
    assert '"provider": "openai"' in html
    assert '"provider": "anthropic"' in html
    assert "filterByProviders" in html
    assert 'id="display-pareto"' in html
    assert 'id="display-full"' in html
    assert 'name="display-mode"' in html
    assert "model-select-display-mode" in html
    assert "function currentDisplayMode" in html


def test_render_report_inlines_split_partials():
    html = render_report(datetime(2026, 9, 7, tzinfo=timezone.utc), SAMPLE_RECORDS, floor=50)
    assert 'id="theme-toggle"' in html
    assert "--thead-bg:" in html
    assert "function initThemeToggle" in html
    assert "function uniqueProviders" in html
    assert 'qwen: "Qwen"' in html
    assert "function filterParetoFrontier" in html
    assert "function renderAll" in html
    assert "var FLOOR = 50;" in html
    assert "{% include" not in html


def test_render_report_embeds_generation_time():
    generated_at = datetime(2026, 9, 7, 12, 34, 56, tzinfo=timezone.utc)
    html = render_report(generated_at, SAMPLE_RECORDS, floor=50)
    assert '<meta name="generated-at" content="2026-09-07T12:34:56+00:00">' in html
    assert '<time datetime="2026-09-07T12:34:56+00:00">2026-09-07 12:34:56 +0000</time>' in html
    assert "生成日時:" in html
