"""Generic string / sequence helpers with no Tavily or I/O dependency.

``slugify`` builds the ``NNNN-<slug>`` file-name stems used across the topic
layout; ``dedupe_preserve_order`` cleans the URL / domain lists the wrappers feed
to the Tavily API. Kept separate from the output contract so both can be reused
(and unit-tested) without importing the heavier writer machinery.
"""

from __future__ import annotations

import re
from collections.abc import Sequence


_SLUG_SEPARATOR = re.compile(r"[^\w]+", re.UNICODE)


def slugify(text: str | None, *, max_length: int = 50) -> str:
    """Turn arbitrary text (a query / domain / title) into a safe file-name stem.

    Collapses runs of non-word characters to single hyphens and lowercases ASCII,
    so ``"Fabric vs Synapse"`` -> ``"fabric-vs-synapse"`` and
    ``"learn.microsoft.com"`` -> ``"learn-microsoft-com"``. Unicode word characters
    (e.g. Japanese) are kept verbatim — they are valid, self-describing file names.
    Empty / punctuation-only input falls back to ``"item"``.
    """
    lowered = (text or "").strip().lower()
    slug = _SLUG_SEPARATOR.sub("-", lowered).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or "item"


def dedupe_preserve_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    normalized_values: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_values.append(normalized)
    return normalized_values
