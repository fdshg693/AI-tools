"""models.json の読み込み・バリデーション。"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from aim_cli import (
    DEFAULT_MODEL,
    MODELS,
    MODELS_CONFIG,
    MODELS_PATH,
    ModelsConfigError,
    load_models,
    main,
    print_model_list,
)


def _write_models(
    path: Path,
    *,
    default: str = "cheap",
    models: dict | None = None,
) -> None:
    if models is None:
        models = {
            "cheap": {
                "enable": True,
                "id": "openai/gpt-oss-120b:free",
                "description": "安い",
            }
        }
    path.write_text(
        json.dumps({"default": default, "models": models}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_committed_models_json_loads() -> None:
    loaded = load_models(MODELS_PATH)
    assert loaded.ids() == MODELS
    assert loaded.default == DEFAULT_MODEL
    assert DEFAULT_MODEL in loaded.models
    assert loaded.models[DEFAULT_MODEL].enable
    assert loaded.models[DEFAULT_MODEL].model_id == MODELS[DEFAULT_MODEL]
    assert all(spec.model_id and spec.description for spec in loaded.models.values())
    assert all(spec.model_id == spec.model_id.strip() for spec in loaded.models.values())
    assert all(isinstance(spec.enable, bool) for spec in loaded.models.values())
    assert MODELS == {alias: spec.model_id for alias, spec in loaded.models.items() if spec.enable}


def test_list_models_prints_aliases_and_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    print_model_list()
    out = capsys.readouterr().out
    for alias, model_id in MODELS.items():
        assert alias in out
        assert model_id in out
    assert "(default)" in out


def test_list_models_cli_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["aim", "--list-models"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for alias, model_id in MODELS.items():
        assert alias in out
        assert model_id in out
    assert "(default)" in out


def test_load_models_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    with pytest.raises(ModelsConfigError, match="見つかりません"):
        load_models(path)


def test_load_models_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ModelsConfigError, match="JSON が不正"):
        load_models(path)


def test_load_models_not_object(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    path.write_text('["gpt-120b"]', encoding="utf-8")
    with pytest.raises(ModelsConfigError, match="空でないオブジェクト"):
        load_models(path)


def test_load_models_empty_object(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ModelsConfigError, match="空でないオブジェクト"):
        load_models(path)


def test_load_models_missing_default(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "models": {
                    "cheap": {
                        "enable": True,
                        "id": "openai/gpt-oss-120b:free",
                        "description": "安い",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ModelsConfigError, match="default が不正"):
        load_models(path)


def test_load_models_non_object_spec(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    _write_models(path, models={"gpt-120b": 1})
    with pytest.raises(ModelsConfigError, match="モデル定義が不正"):
        load_models(path)


def test_load_models_empty_alias(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    _write_models(
        path,
        models={
            "": {"enable": True, "id": "openai/gpt-oss-120b:free", "description": "x"},
            "cheap": {
                "enable": True,
                "id": "openai/gpt-oss-120b:free",
                "description": "安い",
            },
        },
    )
    with pytest.raises(ModelsConfigError, match="略記が不正"):
        load_models(path)


def test_load_models_missing_description(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    _write_models(
        path,
        models={
            "cheap": {
                "enable": True,
                "id": "openai/gpt-oss-120b:free",
                "description": "",
            }
        },
    )
    with pytest.raises(ModelsConfigError, match="description が不正"):
        load_models(path)


def test_load_models_unknown_default(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    _write_models(path, default="missing")
    with pytest.raises(ModelsConfigError, match="default 'missing'"):
        load_models(path)


def test_load_models_strips_id_whitespace(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    _write_models(
        path,
        models={
            "cheap": {
                "enable": True,
                "id": " openai/gpt-oss-120b:free ",
                "description": "安い",
            }
        },
    )
    loaded = load_models(path)
    assert loaded.ids() == {"cheap": "openai/gpt-oss-120b:free"}


def test_load_models_accepts_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    _write_models(path)
    loaded = load_models(path)
    assert loaded.ids() == {"cheap": "openai/gpt-oss-120b:free"}
    assert loaded.default == "cheap"
    assert loaded.models["cheap"].description == "安い"
    assert loaded.models["cheap"].enable is True


def test_load_models_missing_enable(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    _write_models(
        path,
        models={"cheap": {"id": "openai/gpt-oss-120b:free", "description": "安い"}},
    )
    with pytest.raises(ModelsConfigError, match="enable が不正"):
        load_models(path)


def test_load_models_non_bool_enable(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    _write_models(
        path,
        models={
            "cheap": {
                "enable": "true",
                "id": "openai/gpt-oss-120b:free",
                "description": "安い",
            }
        },
    )
    with pytest.raises(ModelsConfigError, match="enable が不正"):
        load_models(path)


def test_load_models_disabled_excluded_from_ids(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    _write_models(
        path,
        default="cheap",
        models={
            "cheap": {
                "enable": True,
                "id": "openai/gpt-oss-120b:free",
                "description": "安い",
            },
            "pricey": {
                "enable": False,
                "id": "openai/gpt-5.6-luna",
                "description": "高い",
            },
        },
    )
    loaded = load_models(path)
    assert loaded.ids() == {"cheap": "openai/gpt-oss-120b:free"}
    assert "pricey" in loaded.models
    assert loaded.models["pricey"].enable is False
    assert list(loaded.enabled_models()) == ["cheap"]


def test_load_models_disabled_default_rejected(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    _write_models(
        path,
        default="cheap",
        models={
            "cheap": {
                "enable": False,
                "id": "openai/gpt-oss-120b:free",
                "description": "安い",
            }
        },
    )
    with pytest.raises(ModelsConfigError, match="enable: false"):
        load_models(path)


def test_ai_help_prints_usage_models_and_descriptions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["aim", "--ai-help"])
    monkeypatch.setattr(
        "aim_cli.resolve_api_key",
        lambda: (_ for _ in ()).throw(AssertionError("APIキーは不要")),
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--prompt" in out
    assert f"デフォルトモデル: {DEFAULT_MODEL}" in out
    for alias, spec in MODELS_CONFIG.enabled_models().items():
        assert alias in out
        assert spec.model_id in out
        assert spec.description in out
    for alias, spec in MODELS_CONFIG.models.items():
        if spec.enable:
            continue
        assert spec.description not in out


def test_help_is_for_humans_and_omits_model_descriptions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["aim", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--prompt" in out
    assert "--ai-help" in out
    assert "人間向け" in out
    for spec in MODELS_CONFIG.models.values():
        assert spec.description not in out


def test_omitted_model_uses_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, str] = {}

    class DummyClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_call(client, model_id, prompt, **kwargs):
        seen["model_id"] = model_id
        seen["prompt"] = prompt
        return "ok"

    monkeypatch.setattr("sys.argv", ["aim", "--prompt", "hi"])
    monkeypatch.setattr("aim_cli.create_client", lambda: DummyClient())
    monkeypatch.setattr("aim_cli.call", fake_call)

    main()
    assert seen["model_id"] == MODELS[DEFAULT_MODEL]
    assert seen["prompt"] == "hi"
    assert capsys.readouterr().out == "ok\n"


def test_version_prints_manifest_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    monkeypatch.setattr("sys.argv", ["aim", "--version"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [f"aim {version}"]


def test_setuptools_py_modules_lists_all_implementation_modules() -> None:
    root = Path(__file__).resolve().parents[1]
    listed = set(
        tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"][
            "py-modules"
        ]
    )
    actual = {path.stem for path in root.glob("aim_*.py")}
    assert listed == actual
