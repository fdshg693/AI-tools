"""自己完結HTML生成（サーバー・JS取得不要。Jinja2テンプレート + 埋め込みJSONで組み立てる）。

bucket分け・表示モード（フル/Pareto）はHTML側の埋め込みJSで動的に行うため、ここではモデルレコードを
JSONとして埋め込むだけで、事前計算は行わない。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

THRESHOLD_DEFAULT = 65
STEP_DEFAULT = 3

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "jinja"]),
)


def render_report(generated_at: datetime, records: list[dict], floor: float) -> str:
    """自己完結HTMLレポートを組み立てる。

    ``records``は``id``/``name``/``provider``/``coding_index``/
    ``price_prompt_per_million``/``price_completion_per_million``の6フィールドを持つ
    フラットなモデルレコードのリスト。``provider``は``id``の``/``前（作成組織 slug）。
    ``floor``はPython側で既に足切り済みの下限値で、HTML側の閾値入力の``min``属性に使う。
    プロバイダ絞り込み・ランク分け（閾値・ステップ）・表示モード（フル/Pareto）はHTML埋め込みJSが担う。
    ``generated_at``は実行時刻。フッタの表示と``<meta name="generated-at">``の両方に埋め込む。
    """
    records_json = json.dumps(records, ensure_ascii=False).replace("</", "<\\/")
    template = _ENV.get_template("report.html.jinja")
    return template.render(
        generated_at_iso=generated_at.isoformat(timespec="seconds"),
        generated_at_display=generated_at.strftime("%Y-%m-%d %H:%M:%S %z"),
        records_json=records_json,
        floor=floor,
        threshold_default=max(THRESHOLD_DEFAULT, floor),
        step_default=STEP_DEFAULT,
    )
