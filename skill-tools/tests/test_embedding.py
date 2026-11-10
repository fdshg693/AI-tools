from __future__ import annotations

import json
from pathlib import Path

import pytest

from skill_tools.index.embedding import (
    EMBEDDING_DIMENSIONS,
    _tool_env_path,
    fetch_embeddings,
    missing_api_key_message,
    resolve_api_key,
)
from skill_tools.models import EmbeddingError


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_fetch_embeddings_uses_independent_contract() -> None:
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((json.loads(request.data), timeout, request.headers["Authorization"]))
        return FakeResponse(
            {
                "data": [
                    {"index": 0, "embedding": [0.0] * EMBEDDING_DIMENSIONS},
                ]
            }
        )

    result = fetch_embeddings(["text"], api_key="secret", urlopen=fake_urlopen)
    assert len(result) == 1
    assert calls[0][0]["model"] == "openai/text-embedding-3-small"
    assert calls[0][2] == "Bearer secret"


def test_embedding_shape_and_key_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse({"data": [{"index": 0, "embedding": [0.0]}]})

    with pytest.raises(EmbeddingError, match="1536"):
        fetch_embeddings(["text"], api_key="secret", urlopen=fake_urlopen)

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("OPENROUTER_API_KEY=fallback\n", encoding="utf-8")
    assert resolve_api_key(env_path) == "fallback"
    assert "OPENROUTER_API_KEY" in missing_api_key_message("OPENROUTER_API_KEY", tmp_path / "none")


def test_default_env_path_is_next_to_tool_package() -> None:
    assert _tool_env_path() == Path(__file__).resolve().parents[1] / ".env"
