"""Offline tests for ``ctx7_core.client``: no network calls.

Every ``requests`` call is replaced by a ``FakeSession`` double that returns a
scripted sequence of ``FakeResponse`` objects, so these tests prove the pure
logic (param building, backoff math, the 429/301/202 policy) without hitting
the real Context7 API. ``time.sleep`` is monkeypatched to a no-op so the
retry/poll tests run instantly instead of actually waiting.

Run (from the repo root, or from this directory):
    uv run pytest tools/ctx7
"""

from __future__ import annotations

from typing import Any

import pytest

from ctx7_core.client import (
    Context7ApiError,
    build_context_params,
    build_search_params,
    compute_backoff_seconds,
    get_context,
    search_libraries,
)


# ---------------------------------------------------------------------------
# Test doubles: a minimal stand-in for requests.Session/requests.get and its
# Response, exposing only what ctx7_core.client actually touches
# (.status_code, .headers, .text, .json(), and Session.get(...)).
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        json_body: Any = None,
        text: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text if text is not None else ("" if json_body is None else "")
        self.headers = headers or {}

    def json(self) -> Any:
        if self._json_body is None:
            raise ValueError("no JSON body on this fake response")
        return self._json_body


class FakeSession:
    """Returns responses from a scripted queue, in order, and records calls."""

    def __init__(self, responses: list[FakeResponse]):
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(
        self, url: str, params: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> FakeResponse:
        self.calls.append(
            {"url": url, "params": dict(params), "headers": dict(headers), "timeout": timeout}
        )
        if not self._responses:
            raise AssertionError("FakeSession ran out of scripted responses")
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this module runs the real retry/poll loops, just instantly."""
    monkeypatch.setattr("ctx7_core.client.time.sleep", lambda _seconds: None)


# ---------------------------------------------------------------------------
# Param building
# ---------------------------------------------------------------------------
def test_build_search_params_defaults_fast_false() -> None:
    params = build_search_params("react", "hooks", fast=False)
    assert params == {"libraryName": "react", "query": "hooks", "fast": "false"}


def test_build_search_params_fast_true() -> None:
    params = build_search_params("react", "hooks", fast=True)
    assert params["fast"] == "true"


def test_build_context_params() -> None:
    params = build_context_params("/react/react", "useEffect cleanup", type_="json", fast=True)
    assert params == {
        "libraryId": "/react/react",
        "query": "useEffect cleanup",
        "type": "json",
        "fast": "true",
    }


# ---------------------------------------------------------------------------
# 429 backoff math (pure function, no sleeping)
# ---------------------------------------------------------------------------
def test_backoff_uses_retry_after_header_when_present() -> None:
    assert compute_backoff_seconds(0, "5") == 5.0
    assert compute_backoff_seconds(2, "5") == 5.0  # Retry-After wins regardless of attempt


def test_backoff_falls_back_to_exponential_without_retry_after() -> None:
    assert compute_backoff_seconds(0, None) == 1.0
    assert compute_backoff_seconds(1, None) == 2.0
    assert compute_backoff_seconds(2, None) == 4.0


def test_backoff_falls_back_to_exponential_on_unparseable_retry_after() -> None:
    assert compute_backoff_seconds(1, "not-a-number") == 2.0


# ---------------------------------------------------------------------------
# search_libraries: success, empty results, error, 429-then-success
# ---------------------------------------------------------------------------
def test_search_libraries_success() -> None:
    session = FakeSession(
        [
            FakeResponse(
                200, json_body={"results": [{"id": "/react/react"}], "searchFilterApplied": False}
            )
        ]
    )
    result = search_libraries("react", "hooks", session=session)
    assert result.status_code == 200
    assert result.data["results"][0]["id"] == "/react/react"
    assert session.calls[0]["params"]["libraryName"] == "react"


def test_search_libraries_omits_auth_header_without_api_key() -> None:
    session = FakeSession([FakeResponse(200, json_body={"results": []})])
    search_libraries("react", "hooks", session=session, api_key=None)
    assert "Authorization" not in session.calls[0]["headers"]


def test_search_libraries_sets_bearer_header_with_api_key() -> None:
    session = FakeSession([FakeResponse(200, json_body={"results": []})])
    search_libraries("react", "hooks", session=session, api_key="secret")
    assert session.calls[0]["headers"]["Authorization"] == "Bearer secret"


def test_search_libraries_raises_on_404() -> None:
    session = FakeSession(
        [FakeResponse(404, json_body={"error": "not_found", "message": "no such library"})]
    )
    with pytest.raises(Context7ApiError) as excinfo:
        search_libraries("nope", "q", session=session)
    assert excinfo.value.status_code == 404
    assert excinfo.value.payload["message"] == "no such library"


def test_search_libraries_retries_once_on_429_then_succeeds() -> None:
    session = FakeSession(
        [
            FakeResponse(
                429,
                headers={"Retry-After": "0"},
                json_body={"error": "rate_limited", "message": "slow down"},
            ),
            FakeResponse(200, json_body={"results": [{"id": "/react/react"}]}),
        ]
    )
    result = search_libraries("react", "hooks", session=session)
    assert result.status_code == 200
    assert len(session.calls) == 2


def test_search_libraries_raises_after_exhausting_429_retries() -> None:
    # MAX_429_RETRIES=3, so 1 initial attempt + 3 retries = 4 total calls before giving up.
    session = FakeSession(
        [FakeResponse(429, json_body={"error": "rate_limited", "message": "still slow"})] * 4
    )
    with pytest.raises(Context7ApiError) as excinfo:
        search_libraries("react", "hooks", session=session)
    assert excinfo.value.status_code == 429
    assert len(session.calls) == 4


# ---------------------------------------------------------------------------
# get_context: type=txt vs type=json bodies, 301 redirect, 202 polling
# ---------------------------------------------------------------------------
def test_get_context_txt_returns_plain_text_body() -> None:
    session = FakeSession([FakeResponse(200, text="## Snippet\n...")])
    result = get_context("/react/react", "useEffect cleanup", type_="txt", session=session)
    assert result.status_code == 200
    assert result.data == "## Snippet\n..."


def test_get_context_json_returns_parsed_body() -> None:
    payload = {"codeSnippets": [], "infoSnippets": [], "rules": []}
    session = FakeSession([FakeResponse(200, json_body=payload)])
    result = get_context("/react/react", "useEffect cleanup", type_="json", session=session)
    assert result.status_code == 200
    assert result.data == payload


def test_get_context_follows_301_redirect_once() -> None:
    session = FakeSession(
        [
            FakeResponse(301, json_body={"redirectUrl": "/react/react/v19"}),
            FakeResponse(200, text="body from the redirected library"),
        ]
    )
    result = get_context("/react/react-old", "q", type_="txt", session=session)
    assert result.status_code == 200
    assert result.data == "body from the redirected library"
    assert len(session.calls) == 2
    assert session.calls[1]["params"]["libraryId"] == "/react/react/v19"


def test_get_context_raises_when_301_has_no_redirect_url() -> None:
    session = FakeSession([FakeResponse(301, json_body={})])
    with pytest.raises(Context7ApiError) as excinfo:
        get_context("/react/react", "q", session=session)
    assert excinfo.value.status_code == 301


def test_get_context_raises_on_second_consecutive_301() -> None:
    # Only one redirect is followed; a second 301 (e.g. a redirect loop) is terminal.
    session = FakeSession(
        [
            FakeResponse(301, json_body={"redirectUrl": "/a/b"}),
            FakeResponse(301, json_body={"redirectUrl": "/c/d"}),
        ]
    )
    with pytest.raises(Context7ApiError) as excinfo:
        get_context("/react/react-old", "q", session=session)
    assert excinfo.value.status_code == 301
    assert len(session.calls) == 2


def test_get_context_polls_202_then_succeeds() -> None:
    session = FakeSession(
        [
            FakeResponse(202, json_body={"status": "indexing"}),
            FakeResponse(200, text="ready now"),
        ]
    )
    result = get_context("/new/lib", "q", type_="txt", session=session)
    assert result.status_code == 200
    assert result.data == "ready now"
    assert len(session.calls) == 2


def test_get_context_returns_202_after_exhausting_polls() -> None:
    # MAX_202_POLLS=3 extra attempts beyond the first -> 4 total calls, all 202.
    session = FakeSession([FakeResponse(202, json_body={"status": "indexing"})] * 4)
    result = get_context("/new/lib", "q", session=session)
    assert result.status_code == 202
    assert result.data == {"status": "indexing"}
    assert len(session.calls) == 4


def test_get_context_raises_on_500() -> None:
    session = FakeSession(
        [FakeResponse(500, json_body={"error": "server_error", "message": "oops"})]
    )
    with pytest.raises(Context7ApiError) as excinfo:
        get_context("/react/react", "q", session=session)
    assert excinfo.value.status_code == 500
