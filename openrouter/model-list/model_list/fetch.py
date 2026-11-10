"""OpenRouter Models API（GET /api/v1/models）呼び出し。"""

from __future__ import annotations

import requests

MODELS_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_SORT = "most-popular"
NEWEST_SORT = "newest"
DEFAULT_LIMIT = 100
CATALOG_LIMIT = 1000
MIN_LIMIT = 1
MAX_LIMIT = 1000


def models_query_params(
    *,
    limit: int = DEFAULT_LIMIT,
    model_authors: str | None = None,
    sort: str = DEFAULT_SORT,
) -> dict[str, str | int]:
    """一覧取得用のクエリ。``sort`` と ``limit`` は常に付ける。"""
    params: dict[str, str | int] = {"sort": sort, "limit": limit}
    if model_authors:
        params["model_authors"] = model_authors
    return params


def catalog_query_params() -> dict[str, int]:
    """作者一覧用。``limit=1000`` でカタログ全件を1リクエストで取る。"""
    return {"limit": CATALOG_LIMIT}


def author_from_model_id(model_id: str) -> str:
    """モデル ID の先頭（``/`` より前）を返す。先頭の ``~`` は除く。"""
    return model_id.lstrip("~").split("/", 1)[0]


def unique_authors(models: list[dict]) -> list[str]:
    """モデル一覧から作者 slug をユニーク化してソートして返す。"""
    authors = {author_from_model_id(model["id"]) for model in models if model.get("id")}
    return sorted(authors)


def _created_timestamp(model: dict) -> float:
    created = model.get("created")
    try:
        return float(created)
    except (TypeError, ValueError):
        return float("-inf")


def filter_by_id(models: list[dict], query: str) -> list[dict]:
    """モデル ID の部分一致（大文字小文字は区別しない）で絞り込む。"""
    needle = query.strip().lower()
    if not needle:
        return list(models)
    return [model for model in models if needle in str(model.get("id", "")).lower()]


def sort_by_newest(models: list[dict]) -> list[dict]:
    """``created``（OpenRouter追加日時）が新しい順。無いものは末尾。"""
    return sorted(models, key=_created_timestamp, reverse=True)


def apply_id_search(models: list[dict], query: str, limit: int) -> list[dict]:
    """ID 部分一致したモデルを新しい順に並べ、先頭 ``limit`` 件を返す。"""
    return sort_by_newest(filter_by_id(models, query))[:limit]


def fetch_models(
    *,
    limit: int = DEFAULT_LIMIT,
    model_authors: str | None = None,
    sort: str = DEFAULT_SORT,
) -> list[dict]:
    """モデル一覧を取得し、レスポンスの``data``配列をそのまま返す。

    既定は人気順。``model_authors``を渡すと作成組織で絞り込む。認証不要。
    ネットワーク例外・非200レスポンスはそのまま呼び出し元に伝播させる。
    """
    response = requests.get(
        MODELS_URL,
        params=models_query_params(limit=limit, model_authors=model_authors, sort=sort),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["data"]


def fetch_catalog() -> list[dict]:
    """作者一覧用にカタログ全件を取得する。``GET /providers`` は呼ばない。"""
    response = requests.get(MODELS_URL, params=catalog_query_params(), timeout=30)
    response.raise_for_status()
    return response.json()["data"]


def pareto_query_params(*, model_authors: str, min_coding_index: float) -> dict[str, str | float]:
    """Pareto 比較用。``sort``/``limit`` は付けず、作者と coding_index 下限だけで取る。"""
    return {"model_authors": model_authors, "min_coding_index": min_coding_index}


def fetch_pareto_models(*, model_authors: str, min_coding_index: float) -> list[dict]:
    """Pareto 比較用のモデル一覧を取得し、レスポンスの``data``配列をそのまま返す。

    認証不要。ネットワーク例外・非200レスポンスはそのまま呼び出し元に伝播させる。
    """
    response = requests.get(
        MODELS_URL,
        params=pareto_query_params(model_authors=model_authors, min_coding_index=min_coding_index),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["data"]
