from model_list.cli import build_parser, main
from model_list.pareto import DEFAULT_MIN_INDEX, PRICE_KEYS


def test_parser_accepts_id_partial_match():
    args = build_parser().parse_args(["--id", "gpt-5", "--limit", "10"])
    assert args.id == "gpt-5"
    assert args.limit == 10


def test_parser_accepts_pareto_options():
    args = build_parser().parse_args(
        ["--pareto", "--provider", "openai,anthropic", "--min-index", "65", "--price", "completion"]
    )
    assert args.pareto is True
    assert args.provider == "openai,anthropic"
    assert args.min_index == 65
    assert args.price == "completion"
    assert args.rebuild is False


def test_parser_rejects_min_index_below_floor():
    parser = build_parser()
    try:
        parser.parse_args(["--pareto", "--min-index", "19"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")


def test_price_without_pareto_errors(capsys):
    try:
        main(["--price", "prompt"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")
    assert "--pareto" in capsys.readouterr().err


def test_min_index_without_pareto_errors(capsys):
    try:
        main(["--min-index", "60"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")
    assert "--min-index" in capsys.readouterr().err


def test_price_choices_match_keys():
    action = next(a for a in build_parser()._actions if "--price" in a.option_strings)
    assert tuple(action.choices) == tuple(PRICE_KEYS)


def test_default_min_index_constant():
    assert DEFAULT_MIN_INDEX == 50
