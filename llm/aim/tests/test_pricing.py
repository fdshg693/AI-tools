"""入力・出力単価の算出と ``--cost`` CLI。HTTP はモックする。"""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO

import pytest

from aim_cli import DEFAULT_MODEL, MODELS, estimate_prompt_cost_usd, get_model_cost, main
from aim_pricing import (
    AimPricingError,
    ModelCost,
    cost_from_model,
    estimate_prompt_tokens,
    fetch_model,
    format_cost_json,
    format_cost_text,
    format_per_million,
    format_usd,
    get_model_cost as pricing_get_model_cost,
    model_url,
    per_million_tokens,
    prompt_cost_usd,
    split_model_id,
    variant_suffix,
    worst_case_price_per_token,
)


class _DummyResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _DummyResponse:
        return self

    def __exit__(self, *_args) -> bool:
        return False


def _http_error(
    code: int, url: str = "https://openrouter.ai/api/v1/model/x/y"
) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", hdrs=None, fp=BytesIO(b""))


def test_no_overrides_returns_base_value() -> None:
    model = {"pricing": {"prompt": "0.000002", "completion": "0.00001"}}
    assert worst_case_price_per_token(model, "prompt") == 0.000002
    assert worst_case_price_per_token(model, "completion") == 0.00001


def test_overrides_present_returns_max_of_base_and_overrides() -> None:
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


def test_override_element_missing_field_is_skipped() -> None:
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
    assert worst_case_price_per_token(model, "completion") == 0.00001
    assert worst_case_price_per_token(model, "prompt") == 0.0000025


def test_base_value_wins_when_higher_than_overrides() -> None:
    model = {
        "pricing": {
            "prompt": "0.00001",
            "completion": "0.00001",
            "overrides": [{"prompt": "0.000004"}],
        }
    }
    assert worst_case_price_per_token(model, "prompt") == 0.00001


def test_per_million_tokens_conversion() -> None:
    assert per_million_tokens(0.000002) == 2.0
    assert per_million_tokens(0.0000004) == 0.4


def test_estimate_prompt_tokens_rounds_up() -> None:
    assert estimate_prompt_tokens("") == 0
    assert estimate_prompt_tokens("abcd") == 1
    assert estimate_prompt_tokens("abcde") == 2


def test_prompt_cost_usd_uses_prompt_rate_only() -> None:
    cost = ModelCost(
        model_id="minimax/minimax-m3", prompt_per_million=0.3, completion_per_million=99.0
    )
    assert prompt_cost_usd(cost, 0) == 0.0
    assert prompt_cost_usd(cost, 1_000_000) == pytest.approx(0.3)
    assert prompt_cost_usd(cost, 2_000) == pytest.approx(0.0006)


def test_format_usd_and_per_million() -> None:
    assert format_usd(0) == "$0"
    assert format_usd(0.0006) == "$0.0006"
    assert format_per_million(0) == "0"
    assert format_per_million(0.3) == "0.3"


def test_cost_from_model_uses_worst_case_per_million() -> None:
    model = {
        "id": "openai/gpt-5.6-luna",
        "pricing": {
            "prompt": "0.0000002",
            "completion": "0.0000012",
            "overrides": [
                {"min_prompt_tokens": 272000, "prompt": "0.0000004", "completion": "0.0000018"}
            ],
        },
    }
    cost = cost_from_model(model)
    assert cost.model_id == "openai/gpt-5.6-luna"
    assert cost.prompt_per_million == 0.4
    assert cost.completion_per_million == 1.8


def test_split_model_id_and_url() -> None:
    assert split_model_id("openai/gpt-oss-120b:free") == ("openai", "gpt-oss-120b:free")
    assert variant_suffix("openai/gpt-oss-120b:free") == "free"
    assert variant_suffix("minimax/minimax-m3") is None
    assert split_model_id("  openai/gpt-5.6-luna  ") == ("openai", "gpt-5.6-luna")
    assert model_url("openai/gpt-5.6-luna ") == (
        "https://openrouter.ai/api/v1/model/openai/gpt-5.6-luna"
    )


def test_split_model_id_rejects_malformed() -> None:
    with pytest.raises(AimPricingError, match="形式が不正"):
        split_model_id("nslash")
    with pytest.raises(AimPricingError, match="形式が不正"):
        split_model_id("/slug")


def test_free_variant_is_zero_without_http(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_fetch(_model_id: str) -> dict:
        raise AssertionError("HTTP を呼んではならない")

    monkeypatch.setattr("aim_pricing.fetch_model", fail_fetch)
    cost = pricing_get_model_cost("openai/gpt-oss-120b:free")
    assert cost.prompt_per_million == 0.0
    assert cost.completion_per_million == 0.0
    assert cost.model_id == "openai/gpt-oss-120b:free"


def test_get_model_cost_fetches_and_keeps_requested_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "aim_pricing.fetch_model",
        lambda model_id: {
            "id": "z-ai/glm-5.2",
            "pricing": {"prompt": "0.000000966", "completion": "0.000003036"},
        },
    )
    cost = pricing_get_model_cost("z-ai/glm-5.2")
    assert cost.model_id == "z-ai/glm-5.2"
    assert cost.prompt_per_million == pytest.approx(0.966)
    assert cost.completion_per_million == pytest.approx(3.036)


def test_get_model_cost_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_fetch(model_id: str) -> dict:
        seen.append(model_id)
        return {"id": model_id, "pricing": {"prompt": "0.000001", "completion": "0.000002"}}

    monkeypatch.setattr("aim_pricing.fetch_model", fake_fetch)
    cost = pricing_get_model_cost(" z-ai/glm-5.3-flash ")
    assert seen == ["z-ai/glm-5.3-flash"]
    assert cost.model_id == "z-ai/glm-5.3-flash"


def test_variant_404_retries_base_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_fetch(model_id: str) -> dict:
        calls.append(model_id)
        if model_id.endswith(":nitro"):
            raise AimPricingError(f"モデルが見つかりません: {model_id}")
        return {"id": model_id, "pricing": {"prompt": "0.000001", "completion": "0.000002"}}

    monkeypatch.setattr("aim_pricing.fetch_model", fake_fetch)
    cost = pricing_get_model_cost("openai/gpt-5.6-luna:nitro")
    assert calls == ["openai/gpt-5.6-luna:nitro", "openai/gpt-5.6-luna"]
    assert cost.model_id == "openai/gpt-5.6-luna:nitro"
    assert cost.prompt_per_million == pytest.approx(1.0)
    assert cost.completion_per_million == pytest.approx(2.0)


def test_fetch_model_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(_request, timeout=30):
        raise _http_error(404)

    monkeypatch.setattr("aim_pricing.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(AimPricingError, match="見つかりません"):
        fetch_model("openai/missing")


def test_fetch_model_reads_data(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(_request, timeout=30):
        return _DummyResponse(
            {
                "data": {
                    "id": "minimax/minimax-m3",
                    "pricing": {"prompt": "0.0000003", "completion": "0.0000012"},
                }
            }
        )

    monkeypatch.setattr("aim_pricing.urllib.request.urlopen", fake_urlopen)
    data = fetch_model("minimax/minimax-m3")
    assert data["id"] == "minimax/minimax-m3"


def test_estimate_prompt_cost_usd_resolves_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(model_id: str):
        return ModelCost(model_id=model_id, prompt_per_million=0.4, completion_per_million=1.8)

    monkeypatch.setattr("aim_pricing.get_model_cost", fake_get)
    usd = estimate_prompt_cost_usd(DEFAULT_MODEL, "a" * 8)
    assert usd == pytest.approx(2 / 1_000_000 * 0.4)


def test_aim_cli_get_model_cost_resolves_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_get(model_id: str):
        seen.append(model_id)
        from aim_pricing import ModelCost

        return ModelCost(model_id=model_id, prompt_per_million=0.3, completion_per_million=1.2)

    monkeypatch.setattr("aim_pricing.get_model_cost", fake_get)
    cost = get_model_cost(DEFAULT_MODEL)
    assert seen == [MODELS[DEFAULT_MODEL]]
    assert cost.prompt_per_million == 0.3


def test_format_cost_text_and_json() -> None:
    from aim_pricing import ModelCost

    cost = ModelCost(
        model_id="openai/gpt-5.6-luna", prompt_per_million=0.4, completion_per_million=1.8
    )
    text = format_cost_text("gpt-luna", cost)
    assert "gpt-luna  openai/gpt-5.6-luna" in text
    assert "0.4 $/M tokens" in text
    assert "1.8 $/M tokens" in text
    parsed = json.loads(format_cost_json("gpt-luna", cost))
    assert parsed["alias"] == "gpt-luna"
    assert parsed["prompt_per_million"] == 0.4
    assert parsed["unit"] == "$/M tokens"


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr("sys.argv", ["aim", *argv])
    with pytest.raises(SystemExit) as exc:
        main()
    return exc.value.code if exc.value.code is not None else 0


def _fail_if_called(*_args, **_kwargs):
    raise AssertionError("本処理（APIキー解決・呼び出し）は --cost 時に走ってはならない")


def test_cost_cli_prints_default_model(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from aim_pricing import ModelCost

    monkeypatch.setattr("aim_cli.resolve_api_key", _fail_if_called)
    monkeypatch.setattr("aim_cli.call", _fail_if_called)
    monkeypatch.setattr(
        "aim_cli.get_model_cost",
        lambda model: ModelCost(
            model_id=MODELS[model],
            prompt_per_million=0.3,
            completion_per_million=1.2,
        ),
    )
    code = _run_main(monkeypatch, ["--cost"])
    assert code == 0
    out = capsys.readouterr().out
    assert DEFAULT_MODEL in out
    assert MODELS[DEFAULT_MODEL] in out
    assert "0.3 $/M tokens" in out
    assert "1.2 $/M tokens" in out


def test_cost_cli_json_for_named_model(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from aim_pricing import ModelCost

    monkeypatch.setattr("aim_cli.resolve_api_key", _fail_if_called)
    monkeypatch.setattr(
        "aim_cli.get_model_cost",
        lambda model: ModelCost(
            model_id=MODELS[model],
            prompt_per_million=0.4,
            completion_per_million=1.8,
        ),
    )
    code = _run_main(monkeypatch, ["--cost", "--model", DEFAULT_MODEL, "--format", "json"])
    assert code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["alias"] == DEFAULT_MODEL
    assert parsed["id"] == MODELS[DEFAULT_MODEL]
    assert parsed["prompt_per_million"] == 0.4
    assert parsed["completion_per_million"] == 1.8


def test_cost_cli_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(_model: str):
        raise AimPricingError("モデルが見つかりません: x")

    monkeypatch.setattr("aim_cli.resolve_api_key", _fail_if_called)
    monkeypatch.setattr("aim_cli.get_model_cost", boom)
    code = _run_main(monkeypatch, ["--cost", "--model", DEFAULT_MODEL])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "見つかりません" in captured.err


def test_cost_cli_free_alias_is_zero_without_http(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("aim_cli.resolve_api_key", _fail_if_called)
    monkeypatch.setattr("aim_pricing.fetch_model", _fail_if_called)
    monkeypatch.setitem(MODELS, "free-test", "vendor/model:free")
    code = _run_main(monkeypatch, ["--cost", "--model", "free-test"])
    assert code == 0
    out = capsys.readouterr().out
    assert "free-test" in out
    assert "vendor/model:free" in out
    assert "prompt      0 $/M tokens" in out
    assert "completion  0 $/M tokens" in out


def test_help_mentions_cost(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["aim", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--cost" in out
