from __future__ import annotations

import pytest

from vscode_profiles.errors import CliError
from vscode_profiles.jsonc import loads


def test_loads_comments_and_trailing_commas() -> None:
    value = loads(
        """
        {
          // line comment
          "editor.fontSize": 14, /* block */
          "url": "http://example.com",
          "items": [1, 2,],
        }
        """
    )
    assert value == {
        "editor.fontSize": 14,
        "url": "http://example.com",
        "items": [1, 2],
    }


def test_unterminated_block_comment_fails() -> None:
    with pytest.raises(CliError, match="comment"):
        loads("{ /* ")
