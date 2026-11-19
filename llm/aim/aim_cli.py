"""OpenRouter経由でAIモデルを呼び出すシンプルなCLI（コマンド名: aim）。"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from openrouter import OpenRouter
from openrouter.errors import OpenRouterError

if TYPE_CHECKING:
    from aim_pricing import AimPricingError, ModelCost

_PRICING_EXPORTS = frozenset(
    {
        "AimPricingError",
        "ModelCost",
        "estimate_prompt_tokens",
        "format_per_million",
        "format_usd",
        "prompt_cost_usd",
    }
)


def __getattr__(name: str):
    if name not in _PRICING_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import aim_pricing as _aim_pricing

    value = getattr(_aim_pricing, name)
    globals()[name] = value
    return value


SCRIPT_DIR = Path(__file__).resolve().parent
ENV_PATH = SCRIPT_DIR / ".env"
MODELS_PATH = SCRIPT_DIR / "models.json"
LOG_DIR = SCRIPT_DIR / "logs"
UNKNOWN_TRACE_TOOL = "unknown"
JOBS_MIN = 1
JOBS_MAX = 10
JOBS_DEFAULT = 4


def tool_version() -> str:
    data = tomllib.loads((SCRIPT_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"]).strip()


class _VersionAction(argparse.Action):
    def __init__(
        self,
        option_strings,
        dest=argparse.SUPPRESS,
        default=argparse.SUPPRESS,
        help="版数を表示して終了する",
    ):
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help,
        )

    def __call__(self, parser, namespace, values, option_string=None):
        print(f"aim {tool_version()}")
        parser.exit(0)


class ModelsConfigError(Exception):
    """models.json の読み込み・バリデーションに失敗した場合。"""


@dataclass(frozen=True)
class ModelSpec:
    """1モデル分の定義（有効フラグ・OpenRouter ID・エージェント向け説明）。"""

    enable: bool
    model_id: str
    description: str


@dataclass(frozen=True)
class ModelsConfig:
    """models.json の内容。略記 → 定義と、省略時に使うデフォルト略記。"""

    default: str
    models: dict[str, ModelSpec]

    def enabled_models(self) -> dict[str, ModelSpec]:
        return {alias: spec for alias, spec in self.models.items() if spec.enable}

    def ids(self) -> dict[str, str]:
        return {alias: spec.model_id for alias, spec in self.enabled_models().items()}


def load_models(path: Path) -> ModelsConfig:
    """models.json からデフォルト略記とモデル定義を読む。

    トップレベルは ``default``（略記）と ``models``（略記 → {enable, id, description}）。
    ``enable`` は真偽値。``id`` / ``description`` は空でない文字列。
    ``default`` は ``enable`` が true の略記でなければならない。
    """
    if not path.is_file():
        raise ModelsConfigError(f"モデル定義ファイルが見つかりません: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ModelsConfigError(f"{path} の JSON が不正です: {e}") from e
    if not isinstance(raw, dict) or not raw:
        raise ModelsConfigError(f"{path} は空でないオブジェクトである必要があります")

    default = raw.get("default")
    if not isinstance(default, str) or not default.strip():
        raise ModelsConfigError(f"{path} の default が不正です: {default!r}")

    models_raw = raw.get("models")
    if not isinstance(models_raw, dict) or not models_raw:
        raise ModelsConfigError(
            f"{path} の models は空でないオブジェクト（略記 → 定義）である必要があります"
        )

    models: dict[str, ModelSpec] = {}
    for alias, spec in models_raw.items():
        if not isinstance(alias, str) or not alias.strip():
            raise ModelsConfigError(f"{path} の略記が不正です: {alias!r}")
        if not isinstance(spec, dict):
            raise ModelsConfigError(f"{path} のモデル定義が不正です（略記 {alias!r}）: {spec!r}")
        enable = spec.get("enable")
        if not isinstance(enable, bool):
            raise ModelsConfigError(f"{path} の enable が不正です（略記 {alias!r}）: {enable!r}")
        model_id = spec.get("id")
        description = spec.get("description")
        if not isinstance(model_id, str) or not model_id.strip():
            raise ModelsConfigError(f"{path} のモデルIDが不正です（略記 {alias!r}）: {model_id!r}")
        model_id = model_id.strip()
        if not isinstance(description, str) or not description.strip():
            raise ModelsConfigError(
                f"{path} の description が不正です（略記 {alias!r}）: {description!r}"
            )
        models[alias] = ModelSpec(enable=enable, model_id=model_id, description=description)

    if default not in models:
        raise ModelsConfigError(f"{path} の default {default!r} は models の略記に含まれていません")
    if not models[default].enable:
        raise ModelsConfigError(f"{path} の default {default!r} は enable: false です")
    return ModelsConfig(default=default, models=models)


# 利用可能なモデル一覧。キーはCLIで指定する略記。定義のSSOTは models.json。
MODELS_CONFIG: ModelsConfig = load_models(MODELS_PATH)
MODELS: dict[str, str] = MODELS_CONFIG.ids()
DEFAULT_MODEL: str = MODELS_CONFIG.default

# --web指定時に有効化するOpenRouter Server Tools（モデルが必要と判断した場合のみ呼ばれる）。
WEB_TOOLS: list[dict] = [
    {"type": "openrouter:web_search"},
    {"type": "openrouter:web_fetch"},
]


def print_model_list() -> None:
    width = max(len(alias) for alias in MODELS)
    for alias, model_id in MODELS.items():
        suffix = "  (default)" if alias == DEFAULT_MODEL else ""
        print(f"{alias.ljust(width)}  {model_id}{suffix}")


def resolve_model_id(model: str) -> str:
    """略記なら OpenRouter ID に変換する。未知の値はそのまま返す。"""
    return MODELS.get(model, model).strip()


def get_model_cost(model: str) -> ModelCost:
    """略記または OpenRouter モデルIDから入力・出力単価を返す。"""
    from aim_pricing import get_model_cost as _get_model_cost

    return _get_model_cost(resolve_model_id(model))


def estimate_prompt_cost_usd(model: str, text: str) -> float:
    """略記またはモデルIDと入力テキストから、入力のみの概算USDを返す。

    単価取得は1回。複数プロンプトを合算したい場合は ``get_model_cost`` を1回呼び、
    各テキストを ``estimate_prompt_tokens`` → ``prompt_cost_usd`` で足す。
    """
    from aim_pricing import estimate_prompt_tokens, prompt_cost_usd

    cost = get_model_cost(model)
    return prompt_cost_usd(cost, estimate_prompt_tokens(text))


def print_model_cost(alias: str, fmt: str | None) -> None:
    from aim_pricing import AimPricingError, format_cost_json, format_cost_text

    try:
        cost = get_model_cost(alias)
    except AimPricingError as e:
        _die(str(e))
    if fmt == "json":
        print(format_cost_json(alias, cost))
    else:
        print(format_cost_text(alias, cost))


def print_ai_help(parser: argparse.ArgumentParser) -> None:
    """エージェント向けに使い方・モデル一覧・説明を標準出力へ出す。"""
    print(parser.format_help().rstrip())
    print()
    print(f"デフォルトモデル: {DEFAULT_MODEL}")
    print()
    print("利用可能なモデル:")
    enabled = MODELS_CONFIG.enabled_models()
    width = max(len(alias) for alias in enabled)
    for alias, spec in enabled.items():
        marker = "  [default]" if alias == DEFAULT_MODEL else ""
        print(f"{alias.ljust(width)}  {spec.model_id}{marker}")
        print(f"  {spec.description}")


def missing_required_key_message(key: str, env_path: Path) -> str:
    env_state = "未設定" if key not in os.environ else "空で設定されている"
    if not env_path.is_file():
        file_state = f"想定した .env は {env_path} ですが、ファイルがありません。"
    else:
        file_state = f"{env_path} はありますが、{key} が無いか空です。"
    return f"{key} が解決できません。\n環境変数 {key} は{env_state}です。\n{file_state}"


def resolve_api_key() -> str:
    load_dotenv(ENV_PATH, override=False)
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if api_key:
        return api_key
    print(missing_required_key_message("OPENROUTER_API_KEY", ENV_PATH), file=sys.stderr)
    sys.exit(1)


def read_prompts(prompt_arg: list[list[str]] | None) -> list[str]:
    """``--prompt`` の値（``action=append`` + ``nargs=+``）または stdin からプロンプト列を取る。"""
    if prompt_arg is not None:
        prompts = [item for group in prompt_arg for item in group]
        if not prompts or any(item == "" for item in prompts):
            print("エラー: プロンプトが空です。", file=sys.stderr)
            sys.exit(1)
        return prompts

    if sys.stdin.isatty():
        print(
            "エラー: プロンプトが指定されていません。"
            "--prompt を指定するか、標準入力から渡してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    prompt = sys.stdin.read().strip()
    if not prompt:
        print("エラー: 標準入力から読み込んだプロンプトが空です。", file=sys.stderr)
        sys.exit(1)
    return [prompt]


def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(getattr(item, "text", "") or "" for item in content)
    return "" if content is None else str(content)


def _log_path_for(record: dict) -> Path:
    """trace.toolごとのフォルダ、日付ごとのファイルにログを振り分ける。

    trace/trace.toolが空の場合は "unknown" フォルダにまとめる。
    """
    trace = record.get("trace") or {}
    tool = trace.get("tool") or UNKNOWN_TRACE_TOOL
    date = record["timestamp"][:10]
    return LOG_DIR / tool / f"{date}.jsonl"


def append_log(record: dict) -> None:
    log_path = _log_path_for(record)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _new_trace_id() -> str:
    """OTel準拠のtrace id（128bit、32桁hex文字列）を生成する。"""
    return secrets.token_hex(16)


def _resolve_trace(trace: dict[str, str] | None) -> dict[str, str]:
    """trace辞書にtrace_idが無ければ生成して補う（呼び出し元指定のtrace_idは尊重する）。

    ここで確定させたtrace_idはOpenRouterへの送信（Grafana Cloud連携時のTrace ID）と
    ローカルログの両方に使われるため、後からGrafana側のトレースと突き合わせられる。
    """
    resolved = dict(trace) if trace else {}
    resolved.setdefault("trace_id", _new_trace_id())
    return resolved


class AimError(Exception):
    """aim経由のOpenRouter API呼び出しが失敗した場合の例外（openrouterへの依存を隠蔽する）。"""


def create_client(api_key: str | None = None) -> OpenRouter:
    """OpenRouterクライアントを生成する。api_key省略時は resolve_api_key() で解決する。"""
    return OpenRouter(api_key=api_key or resolve_api_key())


def _build_log_record(
    model_id: str,
    prompt: str,
    res,
    *,
    user: str | None = None,
    session_id: str | None = None,
    trace: dict[str, str] | None = None,
) -> dict:
    usage = res.usage
    return {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": model_id,
        "prompt": prompt,
        "cost": usage.cost if usage else None,
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
        "total_tokens": usage.total_tokens if usage else None,
        "generation_id": res.id,
        "user": user,
        "session_id": session_id,
        "trace": trace,
    }


def call(
    client: OpenRouter,
    model_id: str,
    prompt: str,
    *,
    web: bool = False,
    user: str | None = None,
    session_id: str | None = None,
    trace: dict[str, str] | None = None,
    return_trace_id: bool = False,
) -> str | tuple[str, str]:
    """OpenRouterへの同期呼び出し（薄いラッパー）。呼び出しごとに calls.jsonl へ記録する。

    trace_id未指定時はこの関数がOTel準拠のtrace idを自動生成し、OpenRouterへの送信・
    ログ記録の両方に使う（Grafana Cloud連携時、ローカルログとGrafana側のトレースを
    trace_idで突き合わせられるようにするため）。
    return_trace_id=Trueの場合、戻り値は (応答テキスト, trace_id) のタプルになる。

    ここにログ等を追加すれば、client/call_async 経由の利用者にも同様の挙動が及ぶ。
    """
    trace = _resolve_trace(trace)
    try:
        res = client.chat.send(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            tools=WEB_TOOLS if web else None,
            user=user,
            session_id=session_id,
            trace=trace,
        )
    except OpenRouterError as e:
        raise AimError(str(e)) from e
    append_log(
        _build_log_record(model_id, prompt, res, user=user, session_id=session_id, trace=trace)
    )
    text = extract_text(res.choices[0].message.content)
    return (text, trace["trace_id"]) if return_trace_id else text


async def call_async(
    client: OpenRouter,
    model_id: str,
    prompt: str,
    *,
    web: bool = False,
    user: str | None = None,
    session_id: str | None = None,
    trace: dict[str, str] | None = None,
    return_trace_id: bool = False,
) -> str | tuple[str, str]:
    """OpenRouterへの非同期呼び出し（薄いラッパー）。call() と同じログ処理・trace_id補完を共有する。"""
    trace = _resolve_trace(trace)
    try:
        res = await client.chat.send_async(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            tools=WEB_TOOLS if web else None,
            user=user,
            session_id=session_id,
            trace=trace,
        )
    except OpenRouterError as e:
        raise AimError(str(e)) from e
    append_log(
        _build_log_record(model_id, prompt, res, user=user, session_id=session_id, trace=trace)
    )
    text = extract_text(res.choices[0].message.content)
    return (text, trace["trace_id"]) if return_trace_id else text


def _die(message: str) -> None:
    print(f"エラー: {message}", file=sys.stderr)
    sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aim",
        description=(
            "OpenRouter経由でAIモデルを呼び出す。応答テキストを標準出力に出す。"
            "プロンプト中の @path はファイル/ディレクトリ内容に展開する。"
            "--parallel は --prompt を複数渡して各プロンプトを別呼び出しにする。"
        ),
        epilog=(
            "例:\n"
            '  aim --prompt "フランスの首都は？"\n'
            '  echo "フランスの首都は？" | aim --model gpt-120b\n'
            '  aim --prompt "@src/foo.py を要約して"\n'
            '  aim --parallel --prompt "@a.py 要約して" "@b.py 要約して"\n'
            "  aim --list-models\n"
            "  aim --cost\n"
            "  aim --cost --model gpt-luna\n"
            "  aim --cost --format json --model glm-5.2"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument(
        "-h",
        "--help",
        action="help",
        help="人間向けの使い方を表示して終了する",
    )
    parser.add_argument("--version", action=_VersionAction)
    parser.add_argument(
        "--model",
        choices=sorted(MODELS),
        default=DEFAULT_MODEL,
        help="利用するモデルの略記（省略時: %(default)s。--list-models で一覧表示）",
    )
    parser.add_argument(
        "--prompt",
        nargs="+",
        action="append",
        default=None,
        metavar="TEXT",
        help=(
            "プロンプト文字列。複数指定は --parallel が必要"
            "（--prompt A B または --prompt A --prompt B）。"
            "省略時は標準入力から1件読む"
        ),
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="利用可能なモデルの一覧（略記とモデルID）を表示して終了する",
    )
    parser.add_argument(
        "--cost",
        action="store_true",
        help=(
            "指定した --model（省略時はデフォルト）の入力・出力単価（$/M tokens）を表示して終了する。"
            "複数価格がある場合は最大値。:free は 0。APIキー不要"
        ),
    )
    parser.add_argument(
        "--ai-help",
        action="store_true",
        help="エージェント向けに使い方・モデル一覧・説明を表示して終了する",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Web Search/Web Fetch（OpenRouter Server Tools）を有効にする（モデルが必要と判断した場合のみ呼ばれる）",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="複数の --prompt を並列に呼び出す（各プロンプトは独立。@path はジョブ区切りではない）",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        help=(f"並列実行数（{JOBS_MIN}〜{JOBS_MAX}、省略時: {JOBS_DEFAULT}）。--parallel 専用"),
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default=None,
        help=(
            "出力形式。未指定かつ --parallel なしは応答本文のみ。"
            "--parallel 時の未指定は markdown。"
            "json は単発でも1要素の配列。"
            "--cost 時は単価の JSON"
        ),
    )
    parser.add_argument(
        "--full-content-names",
        default=None,
        help=(
            "ディレクトリ @path で内容を含めるファイル名のカンマ区切り"
            "（例: SKILL.md,README.md）。省略時は配下の全ファイル内容を含める。"
            "指定した場合、一致しないファイルはツリー listing のパスのみ"
        ),
    )
    return parser


def _run_prompt(args: argparse.Namespace, model_id: str, prompts: list[str]) -> None:
    from aim_files import parse_full_content_names
    from aim_parallel import format_json, format_markdown, make_entry

    if args.jobs is not None and not args.parallel:
        _die("--jobs は --parallel と一緒に指定してください")
    if args.jobs is not None and not (JOBS_MIN <= args.jobs <= JOBS_MAX):
        _die(f"--jobs は{JOBS_MIN}〜{JOBS_MAX}の範囲で指定してください: {args.jobs}")
    if len(prompts) > 1 and not args.parallel:
        _die("複数のプロンプトを渡す場合は --parallel を指定してください")

    cwd = Path.cwd()
    full_content_names = parse_full_content_names(args.full_content_names)

    if args.parallel:
        _run_parallel_prompt(args, model_id, prompts, cwd, full_content_names)
        return

    original = prompts[0]
    expanded, error, refs = _try_expand_prompt(original, cwd, full_content_names)
    if expanded is None:
        _die(error or "プロンプトの展開に失敗しました")

    try:
        with create_client() as client:
            content = call(client, model_id, expanded, web=args.web, trace={"tool": "aim-cli"})
    except AimError as e:
        print(f"エラー: OpenRouter APIの呼び出しに失敗しました: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"エラー: 予期しないエラーが発生しました: {e}", file=sys.stderr)
        sys.exit(1)

    if args.format is None:
        print(content)
        return
    entry = make_entry(
        refs[0].raw_path if refs else "",
        str(refs[0].resolved) if refs else "",
        success=True,
        response=content,
        index=1,
        prompt=original,
    )
    if args.format == "json":
        print(format_json([entry]))
    else:
        print(format_markdown([entry]))


def _try_expand_prompt(
    prompt: str,
    cwd: Path,
    full_content_names: set[str] | None,
) -> tuple[str | None, str | None, list]:
    """``@path`` を本文ブロックへ置換する。失敗時は ``(None, error, refs)``。"""
    from aim_at import AtError, expand_at_refs, find_at_refs
    from aim_files import format_inline_block, read_text_or_error

    try:
        refs = find_at_refs(prompt, cwd)
    except AtError as e:
        return None, str(e), []

    replacements = []
    for ref in refs:
        text, error = read_text_or_error(ref.resolved, full_content_names)
        if text is None:
            return None, error or f"パスの読み込みに失敗しました: {ref.raw_path}", refs
        replacements.append((ref, format_inline_block(ref.raw_path, ref.resolved, text)))
    if replacements:
        prompt = expand_at_refs(prompt, replacements)
    return prompt, None, refs


def _run_parallel_prompt(
    args: argparse.Namespace,
    model_id: str,
    prompts: list[str],
    cwd: Path,
    full_content_names: set[str] | None,
) -> None:
    from aim_parallel import format_json, format_markdown, make_entry, run_parallel

    jobs = args.jobs if args.jobs is not None else JOBS_DEFAULT
    entries = []
    targets: list[tuple[int, str]] = []
    for i, original in enumerate(prompts, start=1):
        expanded, error, refs = _try_expand_prompt(original, cwd, full_content_names)
        if len(prompts) == 1 and len(refs) >= 2:
            print(
                "注意: --parallel でプロンプトが1件です。"
                "複数ジョブにするには --prompt を複数渡してください。"
                ' 例: aim --parallel --prompt "@a.py 要約して" "@b.py 要約して"',
                file=sys.stderr,
            )
        entries.append(
            make_entry(
                refs[0].raw_path if refs else "",
                str(refs[0].resolved) if refs else "",
                success=False,
                error=error,
                index=i,
                prompt=original,
            )
        )
        if expanded is not None:
            targets.append((len(entries) - 1, expanded))

    run_parallel(model_id, jobs, entries, targets, web=args.web)
    fmt = args.format if args.format is not None else "markdown"
    if fmt == "json":
        print(format_json(entries))
    else:
        print(format_markdown(entries))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.ai_help:
        print_ai_help(parser)
        sys.exit(0)

    if args.list_models:
        print_model_list()
        sys.exit(0)

    if args.cost:
        print_model_cost(args.model, args.format)
        sys.exit(0)

    model_id = MODELS[args.model]

    prompts = read_prompts(args.prompt)
    _run_prompt(args, model_id, prompts)


if __name__ == "__main__":
    main()
