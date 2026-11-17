"""PDF via Docling: layout-aware reading order, whole tables, OCR for scanned pages.

Docling runs its own small models on the worker's CPU (layout detection, TableFormer for
table structure, RapidOCR on onnxruntime). They are loaded once per worker process and reused.
No document leaves the machine. Running headers and footers are set aside by Docling's layout
model; watermarks and repeated lines are removed afterwards by parsing.clean.

pypdf still does the cheap checks first (password protection, unreadable file, page cap) and is
the fallback when Docling itself fails on a file.
"""

import io
import logging
import math
import re
import threading
from dataclasses import replace
from typing import Any

from eagleeye_core.config import get_settings
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ingest_worker.errors import PermanentIngestError
from ingest_worker.parsing.base import BBox, ElementKind, ParsedDocument, ParsedElement
from ingest_worker.parsing.pdf import PdfParser, heading_level

logger = logging.getLogger(__name__)

LOW_OCR_CONFIDENCE = 0.5
FIGURE_SCALE = 1.5  # picture crops at 108 dpi: legible for a vision model, small to store
FIGURE_MAX_PX = 1600  # longest side of a saved figure
REPEAT_MIN_PAGES = 3  # a picture on this many pages and half of them is a logo or decoration
_PICTURE_LABELS = frozenset({"picture", "chart"})
# text inside a picture region with this many words is a sentence (a slide's paragraph printed
# over its picture), kept as ordinary text; shorter fragments are the figure's labels
SENTENCE_WORDS = 8
MAX_HEADING_LEVEL = 6

# Docling label -> (our kind, is a heading). Labels not listed (pictures, charts, forms) are
# skipped in this phase; figures arrive with the multimodal plan's Phase 3.
_KINDS: dict[str, ElementKind] = {
    "title": "heading",
    "section_header": "heading",
    "text": "text",
    "paragraph": "text",
    "reference": "text",
    "code": "text",
    "formula": "text",
    "handwritten_text": "text",
    "key_value_region": "text",
    "list_item": "list",
    # checklist lines in forms and publications ("[ ] Deposit FUTA tax if ... over $500")
    "checkbox_selected": "list",
    "checkbox_unselected": "list",
    "caption": "caption",
    "footnote": "footnote",
    "table": "table",
    # tables of contents and indexes: kept as plain lines (see _index_lines), because they hold
    # facts readers ask for ("FUTA tax if undeposited amount is over $500 ... 44")
    "document_index": "text",
}

# dot leaders: "Introduction . . . . . 3" (four or more, so an ellipsis "..." stays)
_LEADER = re.compile(r"(?:\s*\.){4,}\s*")

_converter: Any = None
_converter_lock = threading.Lock()


def _build_converter() -> Any:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        RapidOcrOptions,
        TableFormerMode,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    s = get_settings()
    options = PdfPipelineOptions(
        do_ocr=s.docling_ocr,
        ocr_options=RapidOcrOptions(lang=["latin"]),
        do_table_structure=True,
        generate_picture_images=s.figures_enabled,  # figures are saved and described
        images_scale=FIGURE_SCALE,
        document_timeout=float(s.docling_timeout_s),
    )
    options.table_structure_options.mode = (
        TableFormerMode.ACCURATE if s.docling_table_mode == "accurate" else TableFormerMode.FAST
    )
    if s.docling_artifacts_path:  # models baked into the image (no download at run time)
        options.artifacts_path = s.docling_artifacts_path
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def converter() -> Any:
    global _converter
    with _converter_lock:
        if _converter is None:
            _converter = _build_converter()
        return _converter


def _precheck(data: bytes) -> int:
    """Page count, after the checks Docling would only fail on slowly or vaguely."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise PermanentIngestError("Password-protected PDFs are not supported.")
        pages = len(reader.pages)
    except PdfReadError as exc:
        raise PermanentIngestError("The PDF could not be read.") from exc
    limit = get_settings().pdf_max_pages
    if pages > limit:
        raise PermanentIngestError(
            f"The PDF has {pages} pages; the limit is {limit}. Split it and upload the parts."
        )
    return pages


def _bbox(item: Any) -> tuple[int | None, BBox | None]:
    prov = getattr(item, "prov", None)
    if not prov:
        return None, None
    b = prov[0].bbox
    return prov[0].page_no, (round(b.l, 1), round(b.t, 1), round(b.r, 1), round(b.b, 1))


def _heading_level(label: str, item: Any) -> int:
    if label == "title":
        return 1
    level = getattr(item, "level", 1) or 1  # Docling numbers section headers from 1
    return min(int(level), MAX_HEADING_LEVEL)


def _compact_markdown(markdown: str) -> str:
    """Docling pads every cell to its column width; a wide table is then mostly spaces and
    dashes, which fills the model's reading budget. Same table, one space around each cell."""
    rows = []
    for line in markdown.strip().splitlines():
        cells = [" ".join(cell.split()) for cell in line.strip().strip("|").split("|")]
        if cells and all(cell and set(cell) <= set("-:") for cell in cells):
            cells = ["---"] * len(cells)  # the header rule, shortened
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _index_lines(item: Any) -> str:
    """A table of contents or index as one line per row: the row's distinct cell texts with dot
    leaders removed ("Appendix A. Estimates of Income 15"). As a Markdown table it would be mostly
    dots and cells repeated across columns, which crowds real answers out of the results."""
    lines = []
    for row in item.data.grid:
        cells: list[str] = []
        for cell in row:
            text = _LEADER.sub(" ", cell.text or "").strip()
            if text and text not in cells:
                cells.append(text)
        if cells:
            lines.append(" ".join(cells))
    return "\n".join(lines)


def _parent(item: Any) -> str:
    return getattr(getattr(item, "parent", None), "cref", "") or ""


def _in_picture(item: Any) -> bool:
    return _parent(item).startswith("#/pictures/")


def _png(image: Any) -> bytes:
    image = image.convert("RGB")
    image.thumbnail((FIGURE_MAX_PX, FIGURE_MAX_PX))
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _fingerprint(image: Any) -> str:
    """Average hash (8 x 8): the same logo on every page gets the same value."""
    small = list(image.convert("L").resize((8, 8)).getdata())
    mean = sum(small) / len(small)
    return str(sum(1 << i for i, v in enumerate(small) if v > mean))


def _figure(
    item: Any, document: Any, page: int | None, bbox: BBox | None
) -> tuple[ParsedElement, str] | None:
    """A chart or picture as an image element (+ its fingerprint), or None when it is too small
    or its image is unavailable."""
    s = get_settings()
    if not s.figures_enabled or bbox is None:
        return None
    left, top, right, bottom = bbox
    if min(abs(right - left), abs(top - bottom)) < s.figure_min_points:
        return None
    try:
        image = item.get_image(document)
    except Exception:  # noqa: BLE001 - a picture we cannot crop is kept as its words only
        logger.debug("figure image unavailable", exc_info=True)
        image = None
    if image is None:
        return None
    caption = (item.caption_text(document) or "").strip()
    element = ParsedElement(
        caption or "Figure", page=page, kind="image", bbox=bbox, image_png=_png(image)
    )
    return element, _fingerprint(image)


def _repeated(prints: dict[int, str], elements: list[ParsedElement]) -> set[int]:
    """Indexes of figures whose picture recurs on many pages (logos, decorations)."""
    pages_by_print: dict[str, set[int]] = {}
    for index, fp in prints.items():
        page = elements[index].page
        if page is not None:
            pages_by_print.setdefault(fp, set()).add(page)
    page_count = max((el.page or 0 for el in elements), default=0)
    common = {
        fp
        for fp, pages in pages_by_print.items()
        if len(pages) >= REPEAT_MIN_PAGES and len(pages) * 2 >= page_count
    }
    return {index for index, fp in prints.items() if fp in common}


def to_elements(document: Any) -> list[ParsedElement]:
    """Docling's body items, in reading order, as our elements."""
    elements: list[ParsedElement] = []
    # traverse_pictures: text Docling found inside a picture region is kept. A text block printed
    # over a watermark can be taken for a picture (a whole page was lost that way in the eval),
    # and chart labels sit there too.
    pictures: dict[str, int] = {}  # picture ref -> index of its element (a figure or a word line)
    words: dict[str, list[str]] = {}  # picture ref -> the words printed inside it
    prints: dict[int, str] = {}  # figure element index -> picture fingerprint
    for item, _level in document.iterate_items(with_groups=False, traverse_pictures=True):
        label = getattr(getattr(item, "label", None), "value", "")
        if label in _PICTURE_LABELS:
            page, bbox = _bbox(item)
            ref = getattr(item, "self_ref", "") or f"#/pictures/{len(pictures)}"
            pictures[ref] = len(elements)
            words[ref] = []
            figure = _figure(item, document, page, bbox)
            if figure is None:
                # a picture too small to keep still contributes its words, as one line of text
                elements.append(ParsedElement("", page=page, kind="text", bbox=bbox))
            else:
                prints[len(elements)] = figure[1]
                elements.append(figure[0])
            continue
        kind = _KINDS.get(label)
        if kind is None:
            continue
        page, bbox = _bbox(item)
        if label == "document_index":
            lines = _index_lines(item)
            if lines:
                elements.append(ParsedElement(lines, page=page, kind="text", bbox=bbox))
            continue
        if kind == "table":
            markdown = _compact_markdown(item.export_to_markdown(doc=document))
            if markdown:
                elements.append(
                    ParsedElement(
                        markdown,
                        page=page,
                        kind="table",
                        bbox=bbox,
                        table_html=item.export_to_html(doc=document),
                    )
                )
            continue
        text = _LEADER.sub(" ", getattr(item, "text", "") or "").strip()
        if not text:
            continue
        if _in_picture(item):
            # words inside a chart or diagram ("GOVERN", "RECOVER", axis ticks) belong to it: one
            # line with the figure, never a heading (that filed a whole cover page under "RECOVER")
            if _parent(item) in words and len(text.split()) < SENTENCE_WORDS:
                words[_parent(item)].append(text)
            else:
                elements.append(ParsedElement(text, page=page, kind="text", bbox=bbox))
            continue
        level = _heading_level(label, item) if kind == "heading" else None
        if level is None and kind == "text":
            # the layout model can miss a short heading on a sparse page; the plain-text rule
            # (ALL CAPS or "2.1 Title", short, no end punctuation) still catches it
            level = heading_level(text)
            kind = "heading" if level is not None else kind
        elements.append(ParsedElement(text, page=page, heading_level=level, kind=kind, bbox=bbox))
    for ref, index in pictures.items():
        line = " · ".join(words[ref])
        el = elements[index]
        elements[index] = replace(el, labels=line) if el.kind == "image" else replace(el, text=line)
    drop = _repeated(prints, elements)
    return _continued_tables([el for i, el in enumerate(elements) if el.text and i not in drop])


def _md_rows(markdown: str) -> list[str]:
    return [line for line in markdown.splitlines() if line.strip()]


def _md_cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


_TR = re.compile(r"<tr>.*?</tr>", re.DOTALL)


def _html_with_header(header_html: str, html: str | None) -> str | None:
    """The continuation's rows under the first part's header row; its own first row (taken for a
    header) becomes a data row."""
    if not html:
        return html
    rows = [r.replace("<th", "<td").replace("</th>", "</td>") for r in _TR.findall(html)]
    return f"<table><tbody>{header_html}{''.join(rows)}</tbody></table>"


def _continued_tables(elements: list[ParsedElement]) -> list[ParsedElement]:
    """A table that runs onto the next page comes out of Docling as two tables, and the second
    takes its first data row for a header ("| Ningbo | Montevideo | 40HC | 5,227 |"). Without the
    real header that part is hard to find and to read, so it gets the first part's header row.
    It stays its own element, so its page and position are still right."""
    out: list[ParsedElement] = []
    for el in elements:
        prev = out[-1] if out else None
        if (
            el.kind == "table"
            and prev is not None
            and prev.kind == "table"
            and prev.page is not None
            and el.page == prev.page + 1
        ):
            first, rows = _md_rows(prev.text), _md_rows(el.text)
            if len(first) >= 2 and len(rows) >= 2:
                header, own = first[0], rows[0]
                same_width = len(_md_cells(header)) == len(_md_cells(own))
                if same_width and _md_cells(header) != _md_cells(own):
                    body = [own, *rows[2:]]  # its "header" is a data row; drop its rule line
                    text = "\n".join([header, first[1], *body])
                    header_html = next(iter(_TR.findall(prev.table_html or "")), "")
                    html = _html_with_header(header_html, el.table_html) if header_html else None
                    el = replace(el, text=text, table_html=html or el.table_html)
        out.append(el)
    return out


def _ocr_pages(result: Any) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Pages OCR ran on (a real ocr_score), and those under LOW_OCR_CONFIDENCE. Docling keys
    the confidence report by 1-based page number."""
    pages = getattr(getattr(result, "confidence", None), "pages", None) or {}
    scored = {
        int(no): float(p.ocr_score)
        for no, p in pages.items()
        if p.ocr_score is not None and not math.isnan(float(p.ocr_score))
    }
    ocr = tuple(sorted(scored))
    low = tuple(sorted(n for n, score in scored.items() if score < LOW_OCR_CONFIDENCE))
    return ocr, low


class DoclingPdfParser:
    def __init__(self, fallback: PdfParser | None = None) -> None:
        self._fallback = fallback or PdfParser()

    def parse(self, data: bytes) -> ParsedDocument:
        page_count = _precheck(data)
        try:
            from docling.datamodel.base_models import ConversionStatus, DocumentStream

            result = converter().convert(
                DocumentStream(name="upload.pdf", stream=io.BytesIO(data)), raises_on_error=False
            )
            if result.status not in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
                raise RuntimeError(f"docling status {result.status}")
            elements = to_elements(result.document)
        except PermanentIngestError:
            raise
        except Exception:  # noqa: BLE001 — any Docling failure falls back to plain text
            logger.warning("docling failed on a PDF; falling back to pypdf", exc_info=True)
            return self._fallback.parse(data)
        if not elements:
            raise PermanentIngestError("No text could be found in the PDF, even with OCR.")
        ocr, low = _ocr_pages(result)
        return ParsedDocument(
            tuple(elements),
            page_count=page_count,
            parser="docling",
            ocr_pages=ocr,
            low_confidence_pages=low,
        )
