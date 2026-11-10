"""Shared core for the ``ctx7`` Context7 REST API wrapper.

Two files, split by responsibility the same way ``tav_core`` is (just with
far less surface area, since this package has no output-file layer):

  * ``client``      -- ``requests`` calls to the two Context7 v2 endpoints,
                        the 429/301/202 retry-redirect-poll policy, and the
                        ``ApiResult`` / ``Context7ApiError`` return contract.
  * ``environment``  -- ``.env`` loading + the (optional) API key.
  * ``result_contract`` -- the process exit-code constants.

Import the public surface straight from the package
(``from ctx7_core import get_context, ...``); the names below are
re-exported so ``ctx7_cli`` does not depend on the internal file layout.
"""

from __future__ import annotations

from ctx7_core.client import (
    BASE_URL,
    CONTEXT_PATH,
    DEFAULT_TIMEOUT,
    SEARCH_PATH,
    ApiResult,
    Context7ApiError,
    build_context_params,
    build_search_params,
    compute_backoff_seconds,
    get_context,
    search_libraries,
)
from ctx7_core.environment import (
    API_KEY_ENV,
    get_normalized_api_key,
    load_environment,
)
from ctx7_core.result_contract import (
    EXIT_API_ERROR,
    EXIT_EMPTY_RESULT,
    EXIT_INCOMPLETE,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
)

__all__ = [
    # client
    "BASE_URL",
    "CONTEXT_PATH",
    "DEFAULT_TIMEOUT",
    "SEARCH_PATH",
    "ApiResult",
    "Context7ApiError",
    "build_context_params",
    "build_search_params",
    "compute_backoff_seconds",
    "get_context",
    "search_libraries",
    # environment
    "API_KEY_ENV",
    "get_normalized_api_key",
    "load_environment",
    # result_contract
    "EXIT_API_ERROR",
    "EXIT_EMPTY_RESULT",
    "EXIT_INCOMPLETE",
    "EXIT_RUNTIME_ERROR",
    "EXIT_SUCCESS",
]
