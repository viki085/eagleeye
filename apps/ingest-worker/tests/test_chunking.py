import pytest

from ingest_worker.chunking import MAX_CHARS, PATH_SEP, chunk
from ingest_worker.parsing.base import ParsedElement as E


def _para(n_chars: int, word: str = "lorem") -> str:
    words = (f"{word}{i}." if i % 12 == 11 else f"{word}{i}" for i in range(n_chars))
    text = ""
    for w in words:
        if len(text) + len(w) + 1 > n_chars:
            break
        text = f"{text} {w}" if text else w
    return text


def test_heading_paths_follow_the_stack() -> None:
    els = [
        E("Policy", heading_level=1),
        E(_para(700)),
        E("Returns", heading_level=2),
        E(_para(700)),
        E("Electronics", heading_level=3),
        E(_para(700)),
        E("Shipping", heading_level=2),
        E(_para(700)),
    ]
    paths = [c.heading_path for c in chunk(els)]
    assert paths == [
        ("Policy",),
        ("Policy", "Returns"),
        ("Policy", "Returns", "Electronics"),
        ("Policy", "Shipping"),
    ]


def test_long_section_is_split_with_bounded_size_and_overlap() -> None:
    els = [E("Big", heading_level=1)] + [E(_para(900, f"w{i}x")) for i in range(8)]
    chunks = chunk(els)
    assert len(chunks) > 1
    assert all(len(c.content) <= MAX_CHARS for c in chunks)
    # overlap: the start of chunk n+1 repeats the tail of chunk n
    for a, b in zip(chunks, chunks[1:], strict=False):
        first_words = b.content.split()[:3]
        assert " ".join(first_words) in a.content


def test_no_overlap_between_sections() -> None:
    els = [E("A", heading_level=1), E(_para(800, "alpha")), E("B", heading_level=1), E(_para(800, "beta"))]
    a, b = chunk(els)
    assert "alpha" not in b.content


def test_tiny_sections_merge_into_next_with_inline_title() -> None:
    els = [
        E("Policy", heading_level=1),
        E("Returns", heading_level=2),
        E("Short return rule."),
        E("Shipping", heading_level=2),
        E(_para(800)),
    ]
    chunks = chunk(els)
    assert len(chunks) == 1
    assert chunks[0].heading_path == ("Policy",)
    assert chunks[0].content.startswith("Returns\n\nShort return rule.\n\nShipping")


def test_tiny_top_level_sections_never_merge() -> None:
    els = [
        E("RETURNS", heading_level=1),
        E("Return within 30 days."),
        E("SHIPPING", heading_level=1),
        E("Ships in 3 days."),
    ]
    chunks = chunk(els)
    assert [c.heading_path for c in chunks] == [("RETURNS",), ("SHIPPING",)]


def test_parent_intro_merges_with_child() -> None:
    els = [
        E("Returns", heading_level=1),
        E("Short intro."),
        E("Electronics", heading_level=2),
        E("14 day window."),
    ]
    (only,) = chunk(els)
    assert only.heading_path == ("Returns",)
    assert "Electronics" in only.content


def test_single_huge_paragraph_is_hard_split() -> None:
    chunks = chunk([E("x" * 10_000)])
    assert len(chunks) >= 4
    assert all(len(c.content) <= MAX_CHARS for c in chunks)


def test_page_is_first_page_of_chunk() -> None:
    chunks = chunk([E(_para(700), page=3), E(_para(100), page=4)])
    assert chunks[0].page == 3


def test_hash_is_stable_and_path_sensitive() -> None:
    els = [E("H", heading_level=1), E(_para(700))]
    assert chunk(els)[0].chunk_hash == chunk(els)[0].chunk_hash
    other = [E("Other", heading_level=1), E(_para(700))]
    assert chunk(els)[0].chunk_hash != chunk(other)[0].chunk_hash


def test_numbering_and_empty_input() -> None:
    assert chunk([]) == []
    els = [E(_para(900, f"p{i}x")) for i in range(6)]
    assert [c.chunk_no for c in chunk(els)] == list(range(len(chunk(els))))


def test_invalid_sizes_rejected() -> None:
    with pytest.raises(ValueError):
        chunk([E("x")], max_chars=1000, soft_chars=900, overlap=300)


def test_path_separator_constant() -> None:
    assert PATH_SEP.strip() == "›"
