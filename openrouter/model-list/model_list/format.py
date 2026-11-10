"""表 / JSON 整形。"""

from __future__ import annotations

import json

MODEL_COLUMNS = ("id", "name", "context_length")
PARETO_COLUMNS = ("id", "name", "index", "price")


def model_row(model: dict) -> tuple[str, str, str]:
    model_id = str(model.get("id", ""))
    name = model.get("name")
    context_length = model.get("context_length")
    return (
        model_id,
        model_id if name is None else str(name),
        "" if context_length is None else str(context_length),
    )


def model_record(model: dict) -> dict:
    return {
        "id": model.get("id", ""),
        "name": model.get("name", model.get("id", "")),
        "context_length": model.get("context_length"),
    }


def _align(rows: list[tuple[str, ...]]) -> str:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines: list[str] = []
    for i, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[j]) for j, cell in enumerate(row)))
        if i == 0:
            lines.append("  ".join("-" * widths[j] for j in range(len(widths))))
    return "\n".join(lines)


def format_models_table(models: list[dict]) -> str:
    rows: list[tuple[str, ...]] = [MODEL_COLUMNS]
    rows.extend(model_row(model) for model in models)
    return _align(rows)


def format_models_json(models: list[dict]) -> str:
    return json.dumps([model_record(model) for model in models], ensure_ascii=False, indent=2)


def format_providers_table(providers: list[str]) -> str:
    return "\n".join(providers)


def format_providers_json(providers: list[str]) -> str:
    return json.dumps(providers, ensure_ascii=False, indent=2)


def format_index(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def format_price(value: float) -> str:
    return f"{value:.2f}"


def pareto_row(record: dict, price_key: str) -> tuple[str, str, str, str]:
    return (
        str(record.get("id", "")),
        str(record.get("name", record.get("id", ""))),
        format_index(record["coding_index"]),
        format_price(record[price_key]),
    )


def pareto_record(record: dict, price_key: str) -> dict:
    return {
        "id": record.get("id", ""),
        "name": record.get("name", record.get("id", "")),
        "index": record["coding_index"],
        "price": record[price_key],
    }


def format_pareto_table(records: list[dict], price_key: str) -> str:
    rows: list[tuple[str, ...]] = [PARETO_COLUMNS]
    rows.extend(pareto_row(record, price_key) for record in records)
    return _align(rows)


def format_pareto_json(records: list[dict], price_key: str) -> str:
    return json.dumps(
        [pareto_record(record, price_key) for record in records],
        ensure_ascii=False,
        indent=2,
    )
