"""モデルの入力・出力単価。OpenRouter Models API の pricing を最悪ケース（最大値）で読む。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import quote

TOKENS_PER_MILLION = 1_000_000
# tokenizer を使わない概算。英語コード主体なら 1 token ≈ 4 chars が通例。
CHARS_PER_TOKEN = 4
MODEL_URL_TEMPLATE = "https://openrouter.ai/api/v1/model/{author}/{slug}"
FETCH_TIMEOUT = 30


class AimPricingError(Exception):
    """モデル価格の取得・算出に失敗した場合。"""


@dataclass(frozen=True)
class ModelCost:
    """1モデル分の最悪ケース単価（$/M tokens）。"""

    model_id: str
    prompt_per_million: float
    completion_per_million: float


def worst_case_price_per_token(model: dict, field: str) -> float:
    """モデルの``field``（``"prompt"``または``"completion"``）について、
    ``pricing``のベース値と``pricing.overrides[]``内の同フィールドの最大値を返す（$/token）。

    ``overrides``の各要素は閾値条件（``min_prompt_tokens``等）を持つが、その判定は行わず
    フィールドが存在する要素は常に比較対象に含める。フィールドが無い要素はスキップする。
    """
    pricing = model["pricing"]
    values = [float(pricing[field])]
    for override in pricing.get("overrides", []):
        if field in override:
            values.append(float(override[field]))
    return max(values)


def per_million_tokens(price_per_token: float) -> float:
    """$/token を $/M tokens に変換する。"""
    return float(Decimal(str(price_per_token)) * TOKENS_PER_MILLION)


def estimate_prompt_tokens(text: str) -> int:
    """入力テキストのトークン数を tokenizer なしで概算する（切り上げ）。"""
    if not text:
        return 0
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def prompt_cost_usd(cost: ModelCost, prompt_tokens: int) -> float:
    """入力トークン数だけから USD コストを算出する（出力は含めない）。"""
    if prompt_tokens < 0:
        raise ValueError("prompt_tokens must be >= 0")
    return prompt_tokens / TOKENS_PER_MILLION * cost.prompt_per_million


def format_usd(value: float) -> str:
    """USD 金額を表示用に整形する。"""
    if value == 0:
        return "$0"
    return f"${value:.10f}".rstrip("0").rstrip(".")


def split_model_id(model_id: str) -> tuple[str, str]:
    """``author/slug`` に分割する。slug は ``:free`` 等の variant を含み得る。"""
    model_id = model_id.strip()
    if "/" not in model_id:
        raise AimPricingError(f"モデルIDの形式が不正です: {model_id}")
    author, slug = model_id.split("/", 1)
    if not author.strip() or not slug.strip():
        raise AimPricingError(f"モデルIDの形式が不正です: {model_id}")
    return author.strip(), slug.strip()


def variant_suffix(model_id: str) -> str | None:
    """slug の ``:`` 以降。無ければ None。"""
    _, slug = split_model_id(model_id)
    if ":" not in slug:
        return None
    return slug.rsplit(":", 1)[1]


def model_url(model_id: str) -> str:
    author, slug = split_model_id(model_id)
    return MODEL_URL_TEMPLATE.format(
        author=quote(author, safe=""),
        slug=quote(slug, safe=":"),
    )


def fetch_model(model_id: str, *, timeout: float = FETCH_TIMEOUT) -> dict:
    """``GET /api/v1/model/{author}/{slug}`` の ``data`` オブジェクトを返す。認証不要。"""
    model_id = model_id.strip()
    url = model_url(model_id)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise AimPricingError(f"モデルが見つかりません: {model_id}") from e
        raise AimPricingError(f"OpenRouter Models APIの取得に失敗しました: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise AimPricingError(f"OpenRouter Models APIの取得に失敗しました: {e.reason}") from e
    except TimeoutError as e:
        raise AimPricingError("OpenRouter Models APIの取得がタイムアウトしました") from e
    except json.JSONDecodeError as e:
        raise AimPricingError("OpenRouter Models APIの応答がJSONではありません") from e

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise AimPricingError("OpenRouter Models APIの応答形式が不正です")
    return payload["data"]


def cost_from_model(model: dict) -> ModelCost:
    """Models API のモデルオブジェクトから最悪ケースの入出力単価を算出する。"""
    model_id = model.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        raise AimPricingError("モデル応答に id がありません")
    pricing = model.get("pricing")
    if not isinstance(pricing, dict):
        raise AimPricingError(f"モデル応答に pricing がありません: {model_id}")
    try:
        prompt = worst_case_price_per_token(model, "prompt")
        completion = worst_case_price_per_token(model, "completion")
    except (KeyError, TypeError, ValueError) as e:
        raise AimPricingError(f"pricing から入出力価格を算出できません: {model_id}") from e
    return ModelCost(
        model_id=model_id,
        prompt_per_million=per_million_tokens(prompt),
        completion_per_million=per_million_tokens(completion),
    )


def get_model_cost(model_id: str) -> ModelCost:
    """OpenRouter モデルIDの入力・出力単価を返す（$/M tokens、最悪ケース）。

    ``:free`` variant は Models API に載らないことがあり、呼び出し単価は 0 として扱う。
    その他の variant は完全一致で取得し、404 なら suffix を除いたベース ID を再試行する。
    """
    model_id = model_id.strip()
    suffix = variant_suffix(model_id)
    if suffix == "free":
        return ModelCost(model_id=model_id, prompt_per_million=0.0, completion_per_million=0.0)

    try:
        data = fetch_model(model_id)
    except AimPricingError as e:
        if suffix is None:
            raise
        base_id = model_id.rsplit(":", 1)[0]
        try:
            data = fetch_model(base_id)
        except AimPricingError:
            raise e from None

    cost = cost_from_model(data)
    return ModelCost(
        model_id=model_id,
        prompt_per_million=cost.prompt_per_million,
        completion_per_million=cost.completion_per_million,
    )


def format_per_million(value: float) -> str:
    """$/M tokens の数値を表示用に整形する。"""
    if value == 0:
        return "0"
    return f"{value:.8f}".rstrip("0").rstrip(".")


def format_cost_text(alias: str, cost: ModelCost) -> str:
    width = max(len("prompt"), len("completion"))
    return "\n".join(
        [
            f"{alias}  {cost.model_id}",
            f"{'prompt'.ljust(width)}  {format_per_million(cost.prompt_per_million)} $/M tokens",
            f"{'completion'.ljust(width)}  {format_per_million(cost.completion_per_million)} $/M tokens",
        ]
    )


def format_cost_json(alias: str, cost: ModelCost) -> str:
    return json.dumps(
        {
            "alias": alias,
            "id": cost.model_id,
            "prompt_per_million": cost.prompt_per_million,
            "completion_per_million": cost.completion_per_million,
            "unit": "$/M tokens",
        },
        ensure_ascii=False,
    )
