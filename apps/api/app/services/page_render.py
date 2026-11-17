"""One PDF page as a PNG with a cited passage highlighted (the source panel's "where on the page").

Rendering is CPU work on a file a user uploaded, so it runs in a worker thread, a few at a time,
with a page-size cap. The file was already opened by the same PDFium library at ingest.
"""

import asyncio
import io

import pypdfium2 as pdfium
from PIL import Image, ImageDraw

MAX_SIDE_PX = 1400  # the longer side of the picture
MAX_PAGE_POINTS = 14_400  # 200 inches: anything bigger is not a normal page
PAD_POINTS = 4
FILL = (255, 214, 0, 70)  # translucent yellow
EDGE = (230, 160, 0, 255)
_SLOTS = asyncio.Semaphore(2)

BBox = tuple[float, float, float, float]


class PageRenderError(Exception):
    """The page cannot be shown (not a PDF, no such page, unreadable file)."""


def _box_pixels(bbox: BBox, height: float, scale: float) -> tuple[float, float, float, float]:
    """PDF points to picture pixels. Docling boxes have the origin at the bottom (top > bottom)."""
    left, top, right, bottom = bbox
    if top >= bottom:  # bottom origin: flip to the picture's top origin
        top, bottom = height - top, height - bottom
    return (
        (left - PAD_POINTS) * scale,
        (top - PAD_POINTS) * scale,
        (right + PAD_POINTS) * scale,
        (bottom + PAD_POINTS) * scale,
    )


def render_page(data: bytes, page_no: int, bbox: BBox | None) -> bytes:
    """`page_no` is 1-based, as stored on chunks."""
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise PageRenderError("unreadable PDF") from exc
    try:
        if not 1 <= page_no <= len(pdf):
            raise PageRenderError("no such page")
        page = pdf[page_no - 1]
        width, height = page.get_size()
        if not (0 < width <= MAX_PAGE_POINTS and 0 < height <= MAX_PAGE_POINTS):
            raise PageRenderError("page size out of range")
        scale = MAX_SIDE_PX / max(width, height)
        image = page.render(scale=scale).to_pil().convert("RGBA")
    finally:
        pdf.close()
    if bbox is not None:
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rectangle(
            _box_pixels(bbox, height, scale), fill=FILL, outline=EDGE, width=3
        )
        image = Image.alpha_composite(image, overlay)
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


async def render_page_async(data: bytes, page_no: int, bbox: BBox | None) -> bytes:
    async with _SLOTS:
        return await asyncio.to_thread(render_page, data, page_no, bbox)
