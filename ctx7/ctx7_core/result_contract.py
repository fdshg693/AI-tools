"""Process exit codes for the ctx7 CLI (see README "実行結果 (終了コード)").

Deliberately mirrors ``tools/mslearn/mslearn_core/config.py``'s numbering so a
caller that already knows one of this repo's small wrapper CLIs does not have
to relearn a new scheme: ``0`` success, ``1`` unexpected runtime failure,
``3`` the remote API rejected the call, ``4`` a search came back empty. This
module adds one member mslearn has no equivalent for: ``EXIT_INCOMPLETE``
(``5``), for Context7's "library is still being indexed" (HTTP 202) case,
which is neither an error nor a usable result.

Pure constants -- no I/O, no argparse, no requests. Import straight from here
(``from ctx7_core.result_contract import EXIT_SUCCESS, ...``) or via the
``ctx7_core`` package re-exports.
"""

from __future__ import annotations

EXIT_SUCCESS = 0  # Completed; the result envelope holds the data.
EXIT_RUNTIME_ERROR = 1  # Unexpected failure: connection error, timeout, or any other exception.
EXIT_API_ERROR = 3  # Context7 returned a terminal 4xx/5xx (includes 429 with retries exhausted).
EXIT_EMPTY_RESULT = 4  # `library` succeeded but matched zero candidates.
EXIT_INCOMPLETE = 5  # `docs` stayed at HTTP 202 (indexing) through every poll attempt.
