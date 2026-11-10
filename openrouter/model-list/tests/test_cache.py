import json
from pathlib import Path

from model_list.cache import ensure_cache, fetch_and_store, load_records
from model_list.cli import main
from model_list.pareto import CACHE_FLOOR, DEFAULT_PROVIDERS


def make_api_model(
    model_id: str,
    coding_index: float,
    *,
    prompt: str = "0.000001",
    completion: str = "0.000002",
) -> dict:
    return {
        "id": model_id,
        "name": model_id.split("/", 1)[-1],
        "pricing": {"prompt": prompt, "completion": completion},
        "benchmarks": {"artificial_analysis": {"coding_index": coding_index}},
    }


def write_cache(path: Path, records: list[dict]) -> None:
    path.write_text(
        json.dumps({"records": records}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_load_records_missing_and_corrupt(tmp_path: Path):
    missing = tmp_path / "missing.json"
    assert load_records(missing) is None
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert load_records(corrupt) is None


def test_ensure_cache_reuses_then_rebuilds(monkeypatch, tmp_path: Path):
    path = tmp_path / "pareto.json"
    calls = {"n": 0}

    def fake_fetch(*, model_authors: str, min_coding_index: float) -> list[dict]:
        calls["n"] += 1
        assert model_authors == ",".join(DEFAULT_PROVIDERS)
        assert min_coding_index == CACHE_FLOOR
        return [make_api_model("openai/gpt-5", 71.5)]

    monkeypatch.setattr("model_list.cache.fetch_pareto_models", fake_fetch)
    first = ensure_cache(path)
    second = ensure_cache(path)
    assert calls["n"] == 1
    assert first == second
    assert load_records(path) == first
    ensure_cache(path, rebuild=True)
    assert calls["n"] == 2


def test_fetch_and_store_skips_variants(monkeypatch, tmp_path: Path):
    path = tmp_path / "pareto.json"

    def fake_fetch(**kwargs) -> list[dict]:
        return [
            make_api_model("openai/gpt-5:free", 80),
            make_api_model("openai/gpt-5", 71.5),
        ]

    monkeypatch.setattr("model_list.cache.fetch_pareto_models", fake_fetch)
    records = fetch_and_store(path)
    assert [record["id"] for record in records] == ["openai/gpt-5"]


def test_pareto_reuses_cache_without_fetch(monkeypatch, tmp_path: Path, capsys):
    path = tmp_path / "pareto.json"
    write_cache(
        path,
        [
            {
                "id": "openai/cheap",
                "name": "cheap",
                "provider": "openai",
                "coding_index": 50,
                "price_prompt_per_million": 1.0,
                "price_completion_per_million": 2.0,
            },
            {
                "id": "openai/mid",
                "name": "mid",
                "provider": "openai",
                "coding_index": 60,
                "price_prompt_per_million": 2.0,
                "price_completion_per_million": 3.0,
            },
            {
                "id": "openai/dominated",
                "name": "dominated",
                "provider": "openai",
                "coding_index": 55,
                "price_prompt_per_million": 3.0,
                "price_completion_per_million": 4.0,
            },
        ],
    )

    def boom(**kwargs):
        raise AssertionError("cache hit should not fetch")

    monkeypatch.setattr("model_list.cache.fetch_pareto_models", boom)
    main(["--pareto"], cache_path=path)
    out = capsys.readouterr().out
    assert "openai/cheap" in out
    assert "openai/mid" in out
    assert "openai/dominated" not in out
    lines = out.splitlines()
    assert lines[0].split() == ["id", "name", "index", "price"]
    assert "1.00" in out
    assert "2.00" in out


def test_rebuild_writes_path_and_refetches(monkeypatch, tmp_path: Path, capsys):
    path = tmp_path / "pareto.json"
    write_cache(path, [])
    calls = {"n": 0}

    def fake_fetch(**kwargs) -> list[dict]:
        calls["n"] += 1
        return [make_api_model("google/gemini-2.5-pro", 60, prompt="0.000002")]

    monkeypatch.setattr("model_list.cache.fetch_pareto_models", fake_fetch)
    main(["--rebuild"], cache_path=path)
    captured = capsys.readouterr()
    assert captured.out.strip() == str(path.resolve())
    assert calls["n"] == 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["records"][0]["id"] == "google/gemini-2.5-pro"


def test_pareto_unknown_provider_errors(monkeypatch, tmp_path: Path, capsys):
    path = tmp_path / "pareto.json"

    def boom(**kwargs):
        raise AssertionError("invalid provider should not fetch")

    monkeypatch.setattr("model_list.cache.fetch_pareto_models", boom)
    try:
        main(["--pareto", "--provider", "alibaba"], cache_path=path)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")
    assert "alibaba" in capsys.readouterr().err


def test_pareto_builds_cache_when_missing(monkeypatch, tmp_path: Path, capsys):
    path = tmp_path / "pareto.json"

    def fake_fetch(**kwargs) -> list[dict]:
        return [make_api_model("openai/gpt-5", 71.5, prompt="0.000003")]

    monkeypatch.setattr("model_list.cache.fetch_pareto_models", fake_fetch)
    main(["--pareto"], cache_path=path)
    captured = capsys.readouterr()
    assert path.is_file()
    assert "キャッシュを書きました" in captured.err
    assert "openai/gpt-5" in captured.out
    assert "3.00" in captured.out


def test_pareto_json_uses_selected_price(tmp_path: Path, capsys):
    path = tmp_path / "pareto.json"
    write_cache(
        path,
        [
            {
                "id": "openai/a",
                "name": "A",
                "provider": "openai",
                "coding_index": 50,
                "price_prompt_per_million": 9.0,
                "price_completion_per_million": 1.25,
            }
        ],
    )
    main(["--pareto", "--price", "completion", "--json"], cache_path=path)
    payload = json.loads(capsys.readouterr().out)
    assert payload == [{"id": "openai/a", "name": "A", "index": 50, "price": 1.25}]


def test_pareto_min_index_default_excludes_below_50(tmp_path: Path, capsys):
    path = tmp_path / "pareto.json"
    write_cache(
        path,
        [
            {
                "id": "openai/floor",
                "name": "floor",
                "provider": "openai",
                "coding_index": 20,
                "price_prompt_per_million": 0.5,
                "price_completion_per_million": 0.5,
            },
            {
                "id": "openai/mid",
                "name": "mid",
                "provider": "openai",
                "coding_index": 60,
                "price_prompt_per_million": 1.5,
                "price_completion_per_million": 1.5,
            },
        ],
    )
    main(["--pareto"], cache_path=path)
    default_out = capsys.readouterr().out
    assert "openai/floor" not in default_out
    assert "openai/mid" in default_out
    main(["--pareto", "--min-index", "20"], cache_path=path)
    lowered = capsys.readouterr().out
    assert "openai/floor" in lowered
    assert "openai/mid" in lowered
