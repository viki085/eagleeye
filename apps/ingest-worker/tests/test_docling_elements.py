"""Docling items -> our elements, on fake documents (fixes found with evals/multimodal)."""

from types import SimpleNamespace as NS

from ingest_worker.parsing.docling_pdf import to_elements


def _item(label: str, text: str = "", parent: str = "#/body", page: int = 1, **extra: object) -> NS:
    bbox = NS(l=10.0, t=700.0, r=500.0, b=680.0)
    return NS(
        label=NS(value=label),
        text=text,
        parent=NS(cref=parent),
        prov=[NS(page_no=page, bbox=bbox)],
        **extra,
    )


class FakeDoc:
    def __init__(self, items: list[NS]) -> None:
        self.items = items
        self.traverse_pictures: bool | None = None

    def iterate_items(self, with_groups: bool = False, traverse_pictures: bool = False):  # noqa: ANN201
        self.traverse_pictures = traverse_pictures
        return ((item, 1) for item in self.items)


def test_text_inside_a_picture_is_kept_but_never_becomes_a_heading() -> None:
    doc = FakeDoc(
        [
            _item("text", "RECOVER", parent="#/pictures/0"),
            _item("text", "February 26, 2024", parent="#/pictures/0"),
            _item("text", "RETURNS POLICY"),  # outside a picture: ALL CAPS -> heading
        ]
    )
    elements = to_elements(doc)
    assert doc.traverse_pictures is True  # a page read as a picture is not lost
    assert [(e.text, e.heading_level) for e in elements] == [
        ("RECOVER", None),
        ("February 26, 2024", None),
        ("RETURNS POLICY", 1),
    ]


def test_an_index_becomes_plain_lines_without_dot_leaders_or_repeated_cells() -> None:
    cell = lambda text: NS(text=text)  # noqa: E731
    grid = [
        [cell("Introduction . . . . . . . . . 1"), cell("Introduction . . . . . . . . . 1")],
        [cell("Appendix A. Estimates of Income"), cell(". . . . . . 15")],
    ]
    elements = to_elements(FakeDoc([_item("document_index", data=NS(grid=grid))]))
    assert len(elements) == 1 and elements[0].kind == "text"
    assert elements[0].text == "Introduction 1\nAppendix A. Estimates of Income 15"


def test_checklist_lines_are_kept_with_their_leaders_removed() -> None:
    line = "Deposit FUTA tax if undeposited amount is over $500 . . . . ."
    item = _item("checkbox_unselected", line)
    (element,) = to_elements(FakeDoc([item]))
    assert element.kind == "list"
    assert element.text == "Deposit FUTA tax if undeposited amount is over $500"


def test_an_ellipsis_in_prose_is_left_alone() -> None:
    (element,) = to_elements(FakeDoc([_item("text", "Revenue rose... then fell.")]))
    assert element.text == "Revenue rose... then fell."
