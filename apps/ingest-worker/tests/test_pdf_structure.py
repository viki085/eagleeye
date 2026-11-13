"""PDF structure recovery on real-looking extracted text: slide markers, bullets and
Title Case headings (each switchable, so the retrieval eval can compare them)."""

import pytest
from ingest_worker.parsing.pdf import PdfOptions, is_title_case_heading, page_elements

SLIDES = (
    "Slide 1 of 6\nWelcome To Security\n- Security training must be completed in 10 days.\n"
    "- The course takes about 45 minutes.\nSlide 2 of 6\nPasswords And Access\n"
    "- Passwords need at least 14 characters.\n- Multi-factor authentication is mandatory.\n"
)


def _shape(elements: list) -> list[tuple[str, int | None]]:
    return [(e.text[:24], e.heading_level) for e in elements]


def test_without_options_a_slide_page_is_one_block() -> None:
    els = page_elements(SLIDES, 1, PdfOptions())
    assert len(els) == 1 and els[0].heading_level is None


def test_slide_markers_split_slides_and_titles_become_headings() -> None:
    els = page_elements(SLIDES, 1, PdfOptions(slide_markers=True))
    headings = [e.text for e in els if e.heading_level == 1]
    assert headings == ["Welcome To Security", "Passwords And Access"]
    assert not any("Slide 1 of 6" in e.text for e in els)  # the marker itself is dropped


def test_slide_marker_with_title_on_the_same_line() -> None:
    """Real exports: 'SLIDE 137: Personally Identifiable Information and Data'."""
    text = (
        "SLIDE 137: Personally Identifiable Information and Data\nPII is any data that "
        "identifies a person.\nSlide 138 - Data Masking\nMasking hides values.\n"
    )
    els = page_elements(text, 1, PdfOptions(slide_markers=True))
    assert [e.text for e in els if e.heading_level == 1] == [
        "Personally Identifiable Information and Data",
        "Data Masking",
    ]


def test_bullet_glyphs_extracted_as_control_characters() -> None:
    """pypdf often extracts bullet glyphs as NUL / private-use characters."""
    text = "\x00\x00\x00Encryption at rest\n\x00\x00\x00Access control\n\uf0b7 Audit logging\n"
    els = page_elements(text, 1, PdfOptions(bullets=True))
    assert len(els) == 3


def test_bullets_become_separate_blocks() -> None:
    els = page_elements(SLIDES, 1, PdfOptions(slide_markers=True, bullets=True))
    body = [e.text for e in els if e.heading_level is None]
    assert body[0].startswith("- Security training") and body[1].startswith("- The course")


def test_wrapped_bullet_lines_stay_with_their_bullet() -> None:
    text = "- A long bullet that wraps\nonto a second line.\n- Next bullet."
    els = page_elements(text, 1, PdfOptions(bullets=True))
    assert [e.text for e in els] == [
        "- A long bullet that wraps onto a second line.",
        "- Next bullet.",
    ]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Health Insurance", True),
        ("Time Off", True),
        ("Pension Plan And Savings", True),
        ("Medical cover starts on your first day.", False),  # sentence
        ("the company pays 80 percent", False),  # lowercase
        ("Paris", False),  # a single word is too ambiguous
        ("A Very Long Title Case Line That Goes On And On Past Eight Words Here", False),
        ("Contact: Security Team", False),  # ends a label, has a colon
        ("EUR 1,500 Per Year", False),  # starts with a currency/number
    ],
)
def test_title_case_heading_rule(line: str, expected: bool) -> None:
    assert is_title_case_heading(line) is expected


def test_title_case_headings_only_when_enabled() -> None:
    text = "Health Insurance\nMedical cover starts on your first day of employment.\n"
    off = page_elements(text, 1, PdfOptions())
    on = page_elements(text, 1, PdfOptions(title_case_headings=True))
    assert all(e.heading_level is None for e in off)
    assert _shape(on)[0] == ("Health Insurance", 1)


def test_existing_rules_still_win() -> None:
    text = "2.1 Booking\nFlights must be booked early.\nRETURNS POLICY\nReturn within 30 days.\n"
    els = page_elements(text, 1, PdfOptions(title_case_headings=True))
    assert ("2.1 Booking", 2) in _shape(els) and ("RETURNS POLICY", 1) in _shape(els)
