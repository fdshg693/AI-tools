"""OpenRouter Models API（GET /api/v1/models）呼び出し。"""

from __future__ import annotations

import requests

MODELS_URL = "https://openrouter.ai/api/v1/models"
MODEL_AUTHORS = "openai,anthropic,google,qwen,z-ai,minimax,x-ai,moonshotai,deepseek"


def fetch_models(min_coding_index: float) -> list[dict]:
    """9プロバイダのモデル一覧を取得し、レスポンスの``data``配列をそのまま返す。

    ``min_coding_index``をAPIクエリに渡し、転送量削減のため取得段階でも足切りする
    （``scope.py``側の``minimum``フィルタは安全網として別途残す）。
    認証不要。ネットワーク例外・非200レスポンスはそのまま呼び出し元に伝播させる。
    """
    response = requests.get(
        MODELS_URL,
        params={"model_authors": MODEL_AUTHORS, "min_coding_index": min_coding_index},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["data"]
