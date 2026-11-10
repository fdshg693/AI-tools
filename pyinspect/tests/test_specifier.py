from __future__ import annotations

import pytest

from pyinspect_core.pypi import UsageError, normalize_name, parse_specifier


def test_normalize_collapses_pillow_forms() -> None:
    assert normalize_name("Pillow") == "pillow"
    assert normalize_name("pillow") == "pillow"
    assert normalize_name("PiL_low") == "pil-low"


def test_parse_name_only() -> None:
    spec = parse_specifier("Requests")
    assert spec.name == "Requests"
    assert spec.version is None
    assert spec.pinned is False


def test_parse_pinned_version() -> None:
    spec = parse_specifier("requests==2.32.3")
    assert spec.name == "requests"
    assert spec.version == "2.32.3"
    assert spec.pinned is True


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "requests[security]",
        "requests>=2",
        "requests @ https://example.com/requests.whl",
        "git+https://example.com/repo.git",
        "requests==",
    ],
)
def test_parse_rejects_out_of_scope(raw: str) -> None:
    with pytest.raises(UsageError):
        parse_specifier(raw)
