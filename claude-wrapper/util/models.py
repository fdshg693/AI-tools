"""モデルカタログ（models.json）の読み込みとバリデーション。

claude-wrapper 配下の各スクリプトから共有する。カタログ本体は
このファイルと同じディレクトリの models.json。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CATALOG_FILE = Path(__file__).with_name("models.json")


@dataclass(frozen=True)
class ModelInfo:
    id: str
    resolved: str
    default: bool
    role: str
    evaluation: str


@dataclass(frozen=True)
class ModelCatalog:
    models: tuple[ModelInfo, ...]
    default_id: str
    verified: dict[str, Any]

    def ids(self) -> tuple[str, ...]:
        return tuple(m.id for m in self.models)

    def allowed(self) -> frozenset[str]:
        return frozenset(self.ids())

    def is_allowed(self, model_id: str) -> bool:
        return model_id in self.allowed()

    def get(self, model_id: str) -> ModelInfo | None:
        for item in self.models:
            if item.id == model_id:
                return item
        return None

    def allowed_text(self) -> str:
        return ", ".join(self.ids())

    def prompt_block(self) -> str:
        """エージェントへ渡すカタログ本文。id と評価を並べる。"""
        lines = [
            "利用可能なモデル（カタログの id だけを task.model に書く）:",
        ]
        for item in self.models:
            default_mark = " [default]" if item.default else ""
            role = f" role={item.role}" if item.role else ""
            lines.append(f"- `{item.id}`{default_mark}{role} — {item.evaluation}")
        return "\n".join(lines)


def load_catalog(path: Path | None = None) -> ModelCatalog:
    catalog_path = path or CATALOG_FILE
    if not catalog_path.is_file():
        raise FileNotFoundError(f"モデルカタログがありません: {catalog_path}")
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"モデルカタログが JSON として壊れています: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("モデルカタログはオブジェクトである必要があります")
    raw_models = data.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ValueError("モデルカタログに models 配列がありません")

    models: list[ModelInfo] = []
    seen: set[str] = set()
    defaults: list[str] = []
    for index, raw in enumerate(raw_models):
        item = _parse_model_entry(raw, index)
        if item.id in seen:
            raise ValueError(f"モデル id が重複しています: {item.id!r}")
        seen.add(item.id)
        if item.default:
            defaults.append(item.id)
        models.append(item)

    if len(defaults) != 1:
        raise ValueError(f"default: true のモデルはちょうど 1 件必要です（今は {defaults}）")
    verified = data.get("verified") if isinstance(data.get("verified"), dict) else {}
    return ModelCatalog(
        models=tuple(models),
        default_id=defaults[0],
        verified=verified,
    )


def _parse_model_entry(raw: Any, index: int) -> ModelInfo:
    if not isinstance(raw, dict):
        raise ValueError(f"models[{index}] がオブジェクトではありません")
    model_id = raw.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError(f"models[{index}].id が空です")
    evaluation = raw.get("evaluation")
    if not isinstance(evaluation, str) or not evaluation.strip():
        raise ValueError(f"models[{index}].evaluation が空です（id={model_id!r}）")
    resolved = raw.get("resolved")
    if resolved is None:
        resolved = ""
    elif not isinstance(resolved, str):
        raise ValueError(f"models[{index}].resolved は文字列である必要があります")
    role = raw.get("role")
    if role is None:
        role = ""
    elif not isinstance(role, str):
        raise ValueError(f"models[{index}].role は文字列である必要があります")
    default = raw.get("default", False)
    if not isinstance(default, bool):
        raise ValueError(f"models[{index}].default は boolean である必要があります")
    return ModelInfo(
        id=model_id.strip(),
        resolved=resolved.strip(),
        default=default,
        role=role.strip(),
        evaluation=evaluation.strip(),
    )


def normalize_model(
    value: Any,
    fallback: str,
    catalog: ModelCatalog,
) -> tuple[str | None, str | None]:
    """model をカタログ id に正規化する。空なら fallback。戻り値は (id, error)。"""
    if value is None:
        return fallback, None
    if isinstance(value, str):
        model_id = value.strip()
        if not model_id:
            return fallback, None
    else:
        return None, f"model は文字列である必要があります: {value!r}"
    if not catalog.is_allowed(model_id):
        return None, f"不明な model: {model_id!r}（許可: {catalog.allowed_text()}）"
    return model_id, None


def resolve_task_model(
    task: dict | None,
    fallback: str,
    catalog: ModelCatalog,
) -> tuple[str | None, str | None]:
    if task is None:
        return fallback, None
    return normalize_model(task.get("model"), fallback, catalog)


def invalid_tasks_model_error(tasks: list, catalog: ModelCatalog) -> str | None:
    """todo.json 上の明示 model がカタログ外ならエラー文。省略は許可。"""
    for task in tasks:
        if not isinstance(task, dict):
            continue
        value = task.get("model")
        if value is None or value == "":
            continue
        _, err = normalize_model(value, catalog.default_id, catalog)
        if err:
            return f"id={task.get('id')} {err}"
    return None
