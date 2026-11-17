"""A cited PDF page rendered with its passage highlighted."""

import io

import pypdfium2 as pdfium
import pytest
from app.services.page_render import PageRenderError, _box_pixels, render_page
from PIL import Image


def blank_pdf(pages: int = 2, size: tuple[float, float] = (612, 792)) -> bytes:
    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(*size)
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def test_bottom_origin_boxes_are_flipped_to_the_top() -> None:
    # 72 pt from the left, 100..50 pt from the bottom of a 792 pt page, scale 1
    assert _box_pixels((72, 100, 172, 50), 792, 1.0) == (68, 688, 176, 746)
    assert _box_pixels((72, 50, 172, 100), 792, 2.0) == (136, 92, 352, 208)  # top origin


def test_the_page_is_rendered_with_the_passage_marked() -> None:
    png = render_page(blank_pdf(), 2, (72, 700, 300, 650))
    image = Image.open(io.BytesIO(png))
    assert image.format == "PNG" and max(image.size) == 1400
    scale = 1400 / 792
    inside = image.getpixel((int(150 * scale), int((792 - 675) * scale)))
    outside = image.getpixel((int(450 * scale), int(400 * scale)))
    assert outside == (255, 255, 255)
    assert inside != outside and inside[2] < inside[0]  # yellowish


def test_without_a_box_the_plain_page_is_shown() -> None:
    image = Image.open(io.BytesIO(render_page(blank_pdf(1), 1, None)))
    assert image.getextrema() == ((255, 255), (255, 255), (255, 255))


@pytest.mark.parametrize(
    ("data", "page"),
    [(b"not a pdf", 1), (blank_pdf(1), 2), (blank_pdf(1), 0), (blank_pdf(1, (20000, 20000)), 1)],
)
def test_bad_input_is_refused(data: bytes, page: int) -> None:
    with pytest.raises(PageRenderError):
        render_page(data, page, None)
