"""The chunking defaults in code and in settings must agree (ADR-32 chose them together)."""

from eagleeye_core.config import Settings
from ingest_worker import chunking
from ingest_worker.parsing.pdf import DEFAULT_OPTIONS


def test_settings_defaults_match_the_chunker() -> None:
    s = Settings(_env_file=None)
    assert (s.chunk_max_chars, s.chunk_soft_chars, s.chunk_min_chars, s.chunk_overlap_chars) == (
        chunking.MAX_CHARS,
        chunking.SOFT_CHARS,
        chunking.MIN_CHARS,
        chunking.OVERLAP_CHARS,
    )
    assert s.chunk_soft_chars + s.chunk_overlap_chars + 2 <= s.chunk_max_chars


def test_pdf_defaults_are_the_evaluated_configuration() -> None:
    assert DEFAULT_OPTIONS.slide_markers and DEFAULT_OPTIONS.bullets
    assert not DEFAULT_OPTIONS.title_case_headings
