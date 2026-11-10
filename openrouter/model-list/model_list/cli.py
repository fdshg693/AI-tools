"""``model-list``のエントリポイント。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model_list.cache import CACHE_PATH, ensure_cache, fetch_and_store
from model_list.fetch import (
    CATALOG_LIMIT,
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MIN_LIMIT,
    NEWEST_SORT,
    apply_id_search,
    fetch_catalog,
    fetch_models,
    unique_authors,
)
from model_list.format import (
    format_models_json,
    format_models_table,
    format_pareto_json,
    format_pareto_table,
    format_providers_json,
    format_providers_table,
)
from model_list.pareto import (
    CACHE_FLOOR,
    DEFAULT_MIN_INDEX,
    DEFAULT_PROVIDERS,
    PRICE_KEYS,
    parse_provider_option,
    select_pareto,
    unknown_providers,
)


def _limit_value(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value} は整数ではありません") from exc
    if parsed < MIN_LIMIT or parsed > MAX_LIMIT:
        raise argparse.ArgumentTypeError(
            f"--limit は {MIN_LIMIT}〜{MAX_LIMIT} の範囲で指定してください"
        )
    return parsed


def _min_index_value(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value} は数値ではありません") from exc
    if parsed < CACHE_FLOOR:
        raise argparse.ArgumentTypeError(f"--min-index は {CACHE_FLOOR} 以上で指定してください")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="model-list",
        description="OpenRouter で使えるモデルを人気順に一覧表示する。--pareto で価格と coding_index の Pareto 比較もできる。",
    )
    parser.add_argument(
        "--provider",
        help="作成組織 slug で絞り込む（--list-providers の値。"
        "--pareto 時は openai,anthropic のようにカンマ区切りで複数可）",
    )
    parser.add_argument(
        "--id",
        help="モデル ID の部分一致で絞り込む（大文字小文字は区別しない。新しい順）",
    )
    parser.add_argument(
        "--limit",
        type=_limit_value,
        default=DEFAULT_LIMIT,
        help=f"取得件数（既定 {DEFAULT_LIMIT}、{MIN_LIMIT}〜{MAX_LIMIT}）",
    )
    parser.add_argument(
        "--list-providers",
        action="store_true",
        help="作成組織 slug の一覧を表示して終了する",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="機械可読な JSON で出力する",
    )
    parser.add_argument(
        "--pareto",
        action="store_true",
        help="coding_index と価格の Pareto 最適モデルを表で出す（キャッシュを再利用）",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Pareto 比較用キャッシュを OpenRouter から再取得する",
    )
    parser.add_argument(
        "--min-index",
        type=_min_index_value,
        default=None,
        help=f"Pareto 比較の coding_index 下限（既定 {DEFAULT_MIN_INDEX}、最小 {CACHE_FLOOR}）",
    )
    parser.add_argument(
        "--price",
        choices=tuple(PRICE_KEYS),
        default=None,
        help="Pareto 比較の価格軸（既定 prompt。--pareto 時のみ）",
    )
    return parser


def _run_pareto(
    records: list[dict],
    *,
    provider: str | None,
    min_index: float,
    price_axis: str,
    as_json: bool,
) -> str:
    providers = parse_provider_option(provider)
    price_key = PRICE_KEYS[price_axis]
    rows = select_pareto(
        records,
        providers=providers,
        min_index=min_index,
        price_key=price_key,
    )
    if as_json:
        return format_pareto_json(rows, price_key)
    return format_pareto_table(rows, price_key)


def main(argv: list[str] | None = None, *, cache_path: Path | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    path = CACHE_PATH if cache_path is None else cache_path

    if args.price is not None and not args.pareto:
        parser.error("--price は --pareto と一緒に使ってください")
    if args.min_index is not None and not args.pareto:
        parser.error("--min-index は --pareto と一緒に使ってください")
    if args.pareto and args.id:
        parser.error("--pareto は --id と同時に使えません")
    if args.rebuild and args.id:
        parser.error("--rebuild は --id と同時に使えません")
    if args.pareto and args.list_providers:
        parser.error("--pareto は --list-providers と同時に使えません")
    if args.rebuild and args.list_providers:
        parser.error("--rebuild は --list-providers と同時に使えません")
    if args.pareto:
        providers = parse_provider_option(args.provider)
        if providers:
            unknown = unknown_providers(providers)
            if unknown:
                allowed = ", ".join(DEFAULT_PROVIDERS)
                parser.error(f"不明なプロバイダです: {', '.join(unknown)}（使える値: {allowed}）")

    if args.list_providers:
        providers = unique_authors(fetch_catalog())
        text = format_providers_json(providers) if args.json else format_providers_table(providers)
        print(text)
        return

    if args.rebuild or args.pareto:
        if args.rebuild:
            records = fetch_and_store(path)
            if not args.pareto:
                print(str(path.resolve()))
                return
            print(f"キャッシュを更新しました: {path.resolve()}", file=sys.stderr)
        else:
            existing = path.is_file()
            records = ensure_cache(path)
            if not existing:
                print(f"キャッシュを書きました: {path.resolve()}", file=sys.stderr)
        min_index = DEFAULT_MIN_INDEX if args.min_index is None else args.min_index
        price_axis = "prompt" if args.price is None else args.price
        text = _run_pareto(
            records,
            provider=args.provider,
            min_index=min_index,
            price_axis=price_axis,
            as_json=args.json,
        )
        print(text)
        return

    id_query = (args.id or "").strip()
    if id_query:
        models = apply_id_search(
            fetch_models(
                limit=CATALOG_LIMIT,
                model_authors=args.provider,
                sort=NEWEST_SORT,
            ),
            id_query,
            args.limit,
        )
    else:
        models = fetch_models(limit=args.limit, model_authors=args.provider)
    text = format_models_json(models) if args.json else format_models_table(models)
    print(text)


if __name__ == "__main__":
    main()
