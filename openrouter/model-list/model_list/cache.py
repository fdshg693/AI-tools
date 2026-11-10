"""Pareto 比較用レコードのディスクキャッシュ。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from model_list.fetch import fetch_pareto_models
from model_list.pareto import CACHE_FLOOR, DEFAULT_PROVIDERS, records_from_models

CACHE_PATH = Path(__file__).resolve().parent.parent / "output" / "pareto.json"


def load_records(path: Path) -> list[dict] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    records = payload.get("records")
    if not isinstance(records, list):
        return None
    return records


def fetch_and_store(path: Path) -> list[dict]:
    models = fetch_pareto_models(
        model_authors=",".join(DEFAULT_PROVIDERS),
        min_coding_index=CACHE_FLOOR,
    )
    records = records_from_models(models)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "min_coding_index": CACHE_FLOOR,
        "providers": list(DEFAULT_PROVIDERS),
        "records": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


def ensure_cache(path: Path, *, rebuild: bool = False) -> list[dict]:
    if not rebuild:
        records = load_records(path)
        if records is not None:
            return records
    return fetch_and_store(path)
