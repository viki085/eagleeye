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
from typing import Any

from eagleeye_core.config import get_settings
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ingest_worker.errors import PermanentIngestError
from ingest_worker.parsing.base import BBox, ElementKind, ParsedDocument, ParsedElement
from ingest_worker.parsing.pdf import PdfParser, heading_level

logger = logging.getLogger(__name__)

LOW_OCR_CONFIDENCE = 0.5
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
        generate_picture_images=False,
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


def _in_picture(item: Any) -> bool:
    parent = getattr(getattr(item, "parent", None), "cref", "") or ""
    return parent.startswith("#/pictures/")


def to_elements(document: Any) -> list[ParsedElement]:
    """Docling's body items, in reading order, as our elements."""
    elements: list[ParsedElement] = []
    # traverse_pictures: text Docling found inside a picture region is kept. A text block printed
    # over a watermark can be taken for a picture (a whole page was lost that way in the eval),
    # and chart labels sit there too.
    for item, _level in document.iterate_items(with_groups=False, traverse_pictures=True):
        label = getattr(getattr(item, "label", None), "value", "")
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
            markdown = item.export_to_markdown(doc=document).strip()
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
            # labels inside a diagram or chart ("GOVERN", "RECOVER") are never headings: as
            # headings they would file the rest of the page under a diagram label
            elements.append(ParsedElement(text, page=page, kind="text", bbox=bbox))
            continue
        level = _heading_level(label, item) if kind == "heading" else None
        if level is None and kind == "text":
            # the layout model can miss a short heading on a sparse page; the plain-text rule
            # (ALL CAPS or "2.1 Title", short, no end punctuation) still catches it
            level = heading_level(text)
            kind = "heading" if level is not None else kind
        elements.append(ParsedElement(text, page=page, heading_level=level, kind=kind, bbox=bbox))
    return elements


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
