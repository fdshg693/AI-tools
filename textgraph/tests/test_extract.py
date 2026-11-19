from __future__ import annotations

from textgraph.extract import ExtractedLink, extract_links


def _raws(text: str) -> list[str]:
    return [link.raw for link in extract_links(text)]


def test_extracts_markdown_inline_local_path() -> None:
    links = extract_links("See [guide](../docs/guide.md) please.\n")
    assert links == [ExtractedLink(raw="../docs/guide.md", kind="markdown", line=1)]


def test_extracts_markdown_image() -> None:
    links = extract_links("![alt](./images/diagram.png)\n")
    assert links == [ExtractedLink(raw="./images/diagram.png", kind="image", line=1)]


def test_extracts_reference_definition() -> None:
    links = extract_links("[guide]: ./guide.md\n")
    assert links == [ExtractedLink(raw="./guide.md", kind="ref", line=1)]


def test_extracts_wiki_path_and_labeled_wiki() -> None:
    text = "See [[docs/guide.md]] and [[docs/guide.md|Guide]].\n"
    links = extract_links(text)
    assert [link.kind for link in links] == ["wiki", "wiki"]
    assert _raws(text) == ["docs/guide.md", "docs/guide.md"]


def test_extracts_at_path_at_line_start_and_mid_line() -> None:
    text = "@./README.md\nAlso read @../docs/guide.md later.\n"
    links = extract_links(text)
    assert links == [
        ExtractedLink(raw="./README.md", kind="at", line=1),
        ExtractedLink(raw="../docs/guide.md", kind="at", line=2),
    ]


def test_skips_http_mailto_and_hash_only_targets() -> None:
    text = "[web](https://example.com) [mail](mailto:a@b.com) [here](#section) [ok](./local.md)\n"
    assert _raws(text) == ["./local.md"]


def test_skips_fenced_code_and_inline_backticks() -> None:
    text = (
        "```\n"
        "[hidden](./secret.md)\n"
        "@./hidden.md\n"
        "```\n"
        "Use `[nope](./code.md)` and then [ok](./real.md).\n"
    )
    assert _raws(text) == ["./real.md"]


def test_skips_double_backtick_code_spans() -> None:
    text = "Write ``[[name]]`` or ``a ` [x](./tick.md)`` then [ok](./real.md).\n"
    assert _raws(text) == ["./real.md"]


def test_code_span_closes_only_at_a_run_of_the_same_length() -> None:
    # The ``` run inside does not close the `` span.
    text = "``[a](./a.md) ``` [b](./b.md)`` [c](./c.md)\n"
    assert _raws(text) == ["./c.md"]


def test_unclosed_backtick_run_is_literal_text() -> None:
    # No closing ``: the opening run is skipped whole, not reread as a single `.
    text = "Stray `` then [a](./a.md) and `x` [b](./b.md)\n"
    assert _raws(text) == ["./a.md", "./b.md"]


def test_code_span_does_not_close_across_a_blank_line() -> None:
    # A stray ` must not pair with a backtick in a later paragraph.
    text = "Stray ` tick here.\n\n[a](a.md)\n\n- [b](b.md)\n\n## H\n\nuse `x` ok [c](c.md)\n"
    assert _raws(text) == ["a.md", "b.md", "c.md"]


def test_whitespace_only_line_ends_the_paragraph_for_code_spans() -> None:
    text = "Stray ` tick\r\n  \t\r\n[a](a.md) and `x`\n"
    assert _raws(text) == ["a.md"]


def test_code_span_still_spans_a_line_break_within_a_paragraph() -> None:
    text = "Use `[hidden](./h.md)\nstill code` then [ok](./real.md).\n"
    assert _raws(text) == ["./real.md"]


def test_skips_user_mentions() -> None:
    assert extract_links("Thanks @user and @./README.md\n") == [
        ExtractedLink(raw="./README.md", kind="at", line=1)
    ]


def test_keeps_anchor_in_raw_and_records_line_numbers() -> None:
    text = "Intro\nSee [x](./a.md#section) and [y](./b.md).\n"
    assert extract_links(text) == [
        ExtractedLink(raw="./a.md#section", kind="markdown", line=2),
        ExtractedLink(raw="./b.md", kind="markdown", line=2),
    ]


def test_does_not_double_count_at_path_inside_markdown_url() -> None:
    assert extract_links("[x](@./README.md)\n") == [
        ExtractedLink(raw="@./README.md", kind="markdown", line=1)
    ]
