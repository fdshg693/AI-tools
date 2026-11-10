"""``requests``-based client for the Context7 REST API (v2).

Two endpoints only, matching the two ``ctx7`` subcommands 1:1:

- ``GET /api/v2/libs/search`` -> :func:`search_libraries`
- ``GET /api/v2/context``     -> :func:`get_context`

No SDK, no MCP -- this project talks HTTP directly with ``requests``, the same
"SDK/API directly, thin wrapper" shape as ``tav_core`` (which wraps
``tavily-python``) rather than the MCP-client shape of ``tools/mslearn``.

Response-handling policy (all confirmed against the live API; see the
package's top-level task notes / README "エラー処理" for the source):

- ``200`` success. For ``get_context`` with ``type="txt"`` the body is plain
  text (not JSON) -- everything else (both endpoints' success bodies, and
  every error body regardless of endpoint) is JSON.
- ``202`` (``get_context`` only): the requested library is still being
  indexed. Polled up to :data:`MAX_202_POLLS` extra times, :data:`POLL_INTERVAL_SECONDS`
  apart; if it is still ``202`` afterwards, that body is returned as-is (via
  :class:`ApiResult`, ``status_code=202``) rather than raised, since it is not
  an error -- callers surface this as "try again shortly" (``EXIT_INCOMPLETE``).
- ``301`` (``get_context`` only, observed for stale/aliased library IDs): the
  body's ``redirectUrl`` is the corrected ``libraryId``. Followed exactly
  once -- a second ``301`` after that is treated as a terminal error rather
  than looping.
- ``429``: exponential backoff (:data:`BACKOFF_BASE_SECONDS` doubling each
  attempt), up to :data:`MAX_429_RETRIES` retries, honoring the ``Retry-After``
  response header (seconds) when the server sends one. Retries exhausted ->
  :class:`Context7ApiError`.
- Any other non-200 (``400``/``401``/``403``/``404``/``409``/``422``/``500``/
  ``503``/``504``, or ``429``/``301`` handled above but not resolved) ->
  :class:`Context7ApiError`, carrying the parsed ``{"error", "message"}`` body.

Every function takes an optional ``session`` (anything exposing ``.get(url,
params=..., headers=..., timeout=...)`` -- a ``requests.Session`` or a test
double) so retry/redirect/poll logic is unit-testable without a network call.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

BASE_URL = "https://context7.com/api/v2/"
SEARCH_PATH = "libs/search"
CONTEXT_PATH = "context"

DEFAULT_TIMEOUT = 30.0

# 429 backoff: BACKOFF_BASE_SECONDS * 2**attempt (attempt is 0-based), capped
# at MAX_429_RETRIES retries. Overridden per-attempt by the server's own
# Retry-After header when present (Context7's documented recommendation).
MAX_429_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0

# get_context 202 ("still indexing") polling: MAX_202_POLLS extra attempts
# beyond the first, POLL_INTERVAL_SECONDS apart. Deliberately short/few --
# this is a CLI call, not a background worker; a caller that needs more waits
# by invoking `ctx7 docs` again later.
MAX_202_POLLS = 3
POLL_INTERVAL_SECONDS = 2.0


class Context7ApiError(Exception):
    """A terminal (non-retryable, or retries-exhausted) Context7 API error.

    Carries the HTTP status and the parsed ``{"error", "message"}`` body so a
    caller (the CLI layer) can report both without re-parsing the response.
    """

    def __init__(self, status_code: int, payload: dict[str, Any]):
        self.status_code = status_code
        self.payload = payload
        detail = payload.get("message") or payload.get("error") or f"HTTP {status_code}"
        super().__init__(f"Context7 API error {status_code}: {detail}")


@dataclass(slots=True)
class ApiResult:
    """A successful (non-raised) call outcome.

    ``status_code`` is ``200`` for every :func:`search_libraries` result and
    ordinary :func:`get_context` result, or ``202`` for a :func:`get_context`
    call that stayed "still indexing" through every poll. ``data`` is the
    parsed JSON body, except when ``get_context`` was called with
    ``type_="txt"`` and got a ``200`` -- there ``data`` is the plain-text body
    (a ``str``), per the API's own ``type=txt`` contract.
    """

    status_code: int
    data: Any


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _parse_json_or_error(response: Any) -> dict[str, Any]:
    """Best-effort JSON parse for a non-``200`` (error) response body."""
    try:
        return response.json()
    except ValueError:
        return {"error": "invalid_response", "message": (response.text or "")[:500]}


def compute_backoff_seconds(attempt: int, retry_after: str | None) -> float:
    """Wait time before 429 retry number ``attempt`` (0-based: 0 = first retry).

    Prefers the server's ``Retry-After`` header (seconds, as a plain number
    string) when present and parseable; otherwise falls back to
    ``BACKOFF_BASE_SECONDS * 2**attempt``. Pure function -- no sleeping,
    no I/O -- so retry-timing tests don't need to actually wait.
    """
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return BACKOFF_BASE_SECONDS * (2**attempt)


def build_search_params(library_name: str, query: str, *, fast: bool) -> dict[str, str]:
    return {"libraryName": library_name, "query": query, "fast": "true" if fast else "false"}


def build_context_params(library_id: str, query: str, *, type_: str, fast: bool) -> dict[str, str]:
    return {
        "libraryId": library_id,
        "query": query,
        "type": type_,
        "fast": "true" if fast else "false",
    }


def _get_with_429_retry(
    path: str,
    params: dict[str, str],
    *,
    api_key: str | None,
    timeout: float,
    session: Any = None,
) -> tuple[int, Any]:
    """One logical GET: retries on 429 (see module docstring), returns on anything else.

    Returns ``(status_code, response)`` -- the raw response object, not yet
    parsed, so callers can choose ``.text`` vs ``.json()`` per status/``type``.
    """
    http = session if session is not None else requests
    url = BASE_URL + path

    attempt = 0
    while True:
        response = http.get(url, params=params, headers=_headers(api_key), timeout=timeout)
        status = response.status_code

        if status == 429 and attempt < MAX_429_RETRIES:
            wait = compute_backoff_seconds(attempt, response.headers.get("Retry-After"))
            time.sleep(wait)
            attempt += 1
            continue

        return status, response


def search_libraries(
    library_name: str,
    query: str,
    *,
    fast: bool = False,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    session: Any = None,
) -> ApiResult:
    """``GET /api/v2/libs/search`` -> candidate library IDs.

    Always JSON on success. Raises :class:`Context7ApiError` for any non-200
    (including 429 with retries exhausted).
    """
    params = build_search_params(library_name, query, fast=fast)
    status, response = _get_with_429_retry(
        SEARCH_PATH, params, api_key=api_key, timeout=timeout, session=session
    )
    if status != 200:
        raise Context7ApiError(status, _parse_json_or_error(response))
    return ApiResult(status_code=200, data=response.json())


def get_context(
    library_id: str,
    query: str,
    *,
    type_: str = "txt",
    fast: bool = False,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    session: Any = None,
) -> ApiResult:
    """``GET /api/v2/context`` -> documentation context for one library ID.

    Handles the 301-redirect-once and 202-poll-a-few-times behavior described
    in the module docstring. Returns an :class:`ApiResult` with
    ``status_code`` 200 (success) or 202 (still indexing after every poll);
    raises :class:`Context7ApiError` for any other non-200.
    """
    params = build_context_params(library_id, query, type_=type_, fast=fast)
    redirected = False

    for poll_attempt in range(MAX_202_POLLS + 1):
        status, response = _get_with_429_retry(
            CONTEXT_PATH, params, api_key=api_key, timeout=timeout, session=session
        )

        if status == 301 and not redirected:
            redirect_id = _parse_json_or_error(response).get("redirectUrl")
            if not redirect_id:
                raise Context7ApiError(status, _parse_json_or_error(response))
            params = dict(params, libraryId=redirect_id)
            redirected = True
            status, response = _get_with_429_retry(
                CONTEXT_PATH, params, api_key=api_key, timeout=timeout, session=session
            )

        if status == 200:
            data: Any = response.text if type_ == "txt" else response.json()
            return ApiResult(status_code=200, data=data)

        if status == 202:
            if poll_attempt < MAX_202_POLLS:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            return ApiResult(status_code=202, data=_parse_json_or_error(response))

        raise Context7ApiError(status, _parse_json_or_error(response))

    raise AssertionError("unreachable: the loop above always returns or raises")
