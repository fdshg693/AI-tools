"""``model-select``のエントリポイント。

fetch(floor=50) -> scope(floor=50) -> pricing算出 -> フラットなレコードlist -> render -> ファイル書き出し

プロバイダ絞り込み・bucket分け・Pareto最適フィルタはHTML側（埋め込みJS）で動的に行うため、ここでは行わない。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from model_select.fetch import fetch_models
from model_select.pricing import per_million_tokens, worst_case_price_per_token
from model_select.render import render_report
from model_select.scope import filter_in_scope

CODING_INDEX_FLOOR = 50

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "output" / "report.html"


def _coding_index(model: dict) -> float:
    return model["benchmarks"]["artificial_analysis"]["coding_index"]


def _build_record(model: dict) -> dict:
    model_id = model["id"]
    return {
        "id": model_id,
        "name": model.get("name", model_id),
        "provider": model_id.split("/", 1)[0],
        "coding_index": _coding_index(model),
        "price_prompt_per_million": per_million_tokens(worst_case_price_per_token(model, "prompt")),
        "price_completion_per_million": per_million_tokens(
            worst_case_price_per_token(model, "completion")
        ),
    }


def main() -> None:
    models = filter_in_scope(fetch_models(CODING_INDEX_FLOOR), CODING_INDEX_FLOOR)
    records = [_build_record(model) for model in models]

    html_report = render_report(datetime.now().astimezone(), records, floor=CODING_INDEX_FLOOR)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html_report, encoding="utf-8")
    print(str(OUTPUT_PATH))


if __name__ == "__main__":
    main()
