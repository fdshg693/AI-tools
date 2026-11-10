"""Fail if source uses find_dotenv, usecwd=True, or a pathless load_dotenv().

Those patterns search cwd or parent directories for ``.env``, which violates the
fixed-path ``.env`` rule in ``docs/repo-wide/tool-conventions.md`` (tools that
need upward search use the layered TOML config described there instead).

Exclusions are a path allowlist only (``docs/``, this checker, named fixtures).
A mention in a comment or docstring still fails — do not special-case
prohibition-example wording.

Not wired into lefthook. Run via
``just --justfile tools/internal/justfile tool-env-loading-check``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER_REL_POSIX = "tools/internal/check/check_tool_env_loading.py"

SOURCE_SUFFIXES = frozenset({".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx"})
ALLOWLISTED_PATHS = frozenset({CHECKER_REL_POSIX})
ALLOWLISTED_PREFIXES = (
    "docs/",
    "tools/internal/check/fixtures/",
)

FIND_DOTENV = re.compile(r"\bfind_dotenv\b")
USECWD_TRUE = re.compile(r"\busecwd\s*=\s*True\b")
LOAD_DOTENV_CALL = re.compile(r"\bload_dotenv\s*\(")
DEF_LOAD_DOTENV = re.compile(r"\b(?:async\s+)?def\s+$")
PATH_KEYWORDS = frozenset({"dotenv_path", "path"})


def _is_allowlisted(rel_posix: str) -> bool:
    if rel_posix in ALLOWLISTED_PATHS:
        return True
    return any(rel_posix.startswith(prefix) for prefix in ALLOWLISTED_PREFIXES)


def iter_source_files() -> Iterator[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        rel_posix = raw.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        path = Path(rel_posix)
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if _is_allowlisted(rel_posix):
            continue
        full_path = REPO_ROOT / path
        if full_path.is_file():
            yield full_path


def _line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _line_text(text: str, index: int) -> str:
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    if end == -1:
        end = len(text)
    return text[start:end].rstrip()


def _call_argument_text(text: str, open_paren_index: int) -> str | None:
    depth = 0
    for i, char in enumerate(text[open_paren_index:], start=open_paren_index):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren_index + 1 : i]
    return None


def _first_arg(args: str) -> str:
    depth = 0
    for i, char in enumerate(args):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            return args[:i].strip()
    return args.strip()


def _has_explicit_path(args: str) -> bool:
    first = _first_arg(args)
    if not first:
        return False
    keyword = re.match(r"([A-Za-z_]\w*)\s*=", first)
    if keyword:
        return keyword.group(1) in PATH_KEYWORDS
    return True


def find_violations(text: str) -> list[tuple[int, str, str]]:
    """Return (line_number, pattern_name, line_text) hits in ``text``."""
    hits: list[tuple[int, str, str]] = []
    seen: set[tuple[int, str]] = set()

    def add(index: int, pattern_name: str) -> None:
        line_no = _line_number(text, index)
        key = (line_no, pattern_name)
        if key in seen:
            return
        seen.add(key)
        hits.append((line_no, pattern_name, _line_text(text, index)))

    for match in FIND_DOTENV.finditer(text):
        add(match.start(), "find_dotenv")
    for match in USECWD_TRUE.finditer(text):
        add(match.start(), "usecwd=True")
    for match in LOAD_DOTENV_CALL.finditer(text):
        if DEF_LOAD_DOTENV.search(text[: match.start()]):
            continue
        args = _call_argument_text(text, match.end() - 1)
        if args is None or _has_explicit_path(args):
            continue
        add(match.start(), "load_dotenv() without path")
    hits.sort()
    return hits


def collect_violations() -> list[tuple[str, int, str, str]]:
    failures: list[tuple[str, int, str, str]] = []
    for path in iter_source_files():
        text = path.read_text(encoding="utf-8")
        rel_posix = path.relative_to(REPO_ROOT).as_posix()
        for line_no, pattern_name, line_text in find_violations(text):
            failures.append((rel_posix, line_no, pattern_name, line_text))
    return failures


def main(argv: list[str]) -> int:
    del argv
    failures = collect_violations()

    if failures:
        print(
            "Source uses cwd/parent .env search (find_dotenv / usecwd=True / "
            "pathless load_dotenv()). Use a fixed path: "
            "load_dotenv(ENV_PATH, override=False). "
            "See docs/repo-wide/tool-conventions.md.",
            file=sys.stderr,
        )
        for rel_posix, line_no, pattern_name, line_text in failures:
            print(
                f"  - {rel_posix}:{line_no}: {pattern_name}: {line_text}",
                file=sys.stderr,
            )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
