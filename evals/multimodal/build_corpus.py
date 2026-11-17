"""Builds the multimodal PDF test set (Phase 0 of the multimodal RAG plan).

  evals/multimodal/.venv/Scripts/python.exe evals/multimodal/build_corpus.py

Sources are public-domain US government PDFs (downloaded into pdfs/, git-ignored). From them it
writes corpus/: page excerpts plus three kinds of hard variants, and corpus/manifest.json:
  scanned    every page rasterized (no text layer), slightly skewed: needs OCR
  mixed      first pages rasterized, the rest normal text: needs per-page OCR
  watermark  diagonal "CONFIDENTIAL" plus a "DRAFT" footer on every page
  deck       chart pages rendered as images with only a short title: "image-heavy"
"""

import io
import json
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color
from reportlab.pdfgen import canvas

ROOT = Path(__file__).parent
PDFS = ROOT / "pdfs"
OUT = ROOT / "corpus"
UA = "Mozilla/5.0 (eval-fetch)"
SCAN_DPI = 150
SKEW_DEG = 0.6
WATERMARK = "CONFIDENTIAL"
FOOTER = "DRAFT - INTERNAL USE ONLY"


@dataclass(frozen=True)
class Source:
    name: str
    url: str


SOURCES = {
    s.name: s
    for s in [
        Source("eia_steo", "https://www.eia.gov/outlooks/steo/pdf/steo_full.pdf"),
        Source("bls_empsit", "https://www.bls.gov/news.release/pdf/empsit.pdf"),
        Source("census_income", "https://www2.census.gov/library/publications/2024/demo/p60-282.pdf"),
        Source("fed_mpr", "https://www.federalreserve.gov/monetarypolicy/files/20250620_mprfullreport.pdf"),
        Source("irs_p15", "https://www.irs.gov/pub/irs-pdf/p15.pdf"),
        Source("irs_f1040", "https://www.irs.gov/pub/irs-pdf/f1040.pdf"),
        Source("nhc_ian", "https://www.nhc.noaa.gov/data/tcr/AL092022_Ian.pdf"),
        Source("nist_csf2", "https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf"),
        Source("usgs_copper", "https://pubs.usgs.gov/periodicals/mcs2024/mcs2024-copper.pdf"),
        Source("usgs_lithium", "https://pubs.usgs.gov/periodicals/mcs2024/mcs2024-lithium.pdf"),
    ]
}

# (output slug, source, 1-based pages, kind)
DOCS: list[tuple[str, str, list[int], str]] = [
    ("eia_steo", "eia_steo", list(range(1, 11)), "text"),
    ("deck_eia_charts", "eia_steo", list(range(11, 21)), "deck"),
    ("bls_empsit_mixed", "bls_empsit", list(range(1, 11)), "mixed"),
    ("census_income_wm", "census_income", list(range(1, 13)), "watermark"),
    ("fed_mpr", "fed_mpr", list(range(1, 13)), "text"),
    ("irs_p15", "irs_p15", list(range(1, 11)), "text"),
    ("nhc_ian", "nhc_ian", list(range(1, 7)) + list(range(55, 63)), "text"),
    ("nist_csf2_wm", "nist_csf2", list(range(1, 13)), "watermark"),
    ("usgs_copper_scan", "usgs_copper", [1, 2], "scanned"),
    ("usgs_lithium", "usgs_lithium", [1, 2], "text"),
    ("irs_f1040_scan", "irs_f1040", [1, 2], "scanned"),
]
MIXED_RASTER_PAGES = 3  # first pages of a "mixed" document lose their text layer


def fetch(src: Source) -> Path:
    path = PDFS / f"{src.name}.pdf"
    if not path.exists():
        PDFS.mkdir(exist_ok=True)
        req = urllib.request.Request(src.url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            path.write_bytes(resp.read())
    return path


def excerpt(path: Path, pages: list[int]) -> bytes:
    reader = PdfReader(path)
    writer = PdfWriter()
    for p in pages:
        if p <= len(reader.pages):
            writer.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def render_pages(data: bytes, dpi: int = SCAN_DPI) -> list[Image.Image]:
    doc = pdfium.PdfDocument(data)
    try:
        return [doc[i].render(scale=dpi / 72).to_pil() for i in range(len(doc))]
    finally:
        doc.close()


def as_scan(img: Image.Image) -> Image.Image:
    gray = img.convert("L")
    return gray.rotate(SKEW_DEG, expand=False, fillcolor=255, resample=Image.BICUBIC)


def images_to_pdf(images: list[Image.Image]) -> bytes:
    buf = io.BytesIO()
    first, *rest = images
    first.save(buf, format="PDF", save_all=True, append_images=rest, resolution=SCAN_DPI)
    return buf.getvalue()


def scanned(data: bytes) -> bytes:
    return images_to_pdf([as_scan(i) for i in render_pages(data)])


def mixed(data: bytes, raster_pages: int) -> bytes:
    scan = PdfReader(io.BytesIO(scanned(excerpt_bytes(data, range(raster_pages)))))
    src = PdfReader(io.BytesIO(data))
    writer = PdfWriter()
    for i, page in enumerate(src.pages):
        writer.add_page(scan.pages[i] if i < raster_pages else page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def excerpt_bytes(data: bytes, indexes: range) -> bytes:
    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter()
    for i in indexes:
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def watermark_page(width: float, height: float) -> PdfReader:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.setFillColor(Color(0.6, 0.6, 0.6, alpha=0.25))
    c.setFont("Helvetica-Bold", min(width, height) / 7)
    c.translate(width / 2, height / 2)
    c.rotate(45)
    c.drawCentredString(0, 0, WATERMARK)
    c.rotate(-45)
    c.translate(-width / 2, -height / 2)
    c.setFillColor(Color(0.4, 0.4, 0.4, alpha=0.8))
    c.setFont("Helvetica", 8)
    c.drawCentredString(width / 2, 14, FOOTER)
    c.save()
    return PdfReader(io.BytesIO(buf.getvalue()))


def watermarked(data: bytes) -> bytes:
    writer = PdfWriter(clone_from=io.BytesIO(data))
    for page in writer.pages:
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        page.merge_page(watermark_page(w, h).pages[0])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def deck(data: bytes, title: str) -> bytes:
    """Each page as a full-bleed image with one short text title on top (image-heavy)."""
    images = render_pages(data, dpi=110)
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i, img in enumerate(images, start=1):
        w, h = img.size
        c.setPageSize((w, h + 40))
        tmp = io.BytesIO()
        img.convert("RGB").save(tmp, format="JPEG", quality=85)
        tmp.seek(0)
        from reportlab.lib.utils import ImageReader

        c.drawImage(ImageReader(tmp), 0, 0, width=w, height=h)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(20, h + 14, f"{title} - slide {i}")
        c.showPage()
    c.save()
    return buf.getvalue()


BUILDERS = {
    "text": lambda d, _slug: d,
    "scanned": lambda d, _slug: scanned(d),
    "mixed": lambda d, _slug: mixed(d, MIXED_RASTER_PAGES),
    "watermark": lambda d, _slug: watermarked(d),
    "deck": lambda d, _slug: deck(d, "Energy outlook charts"),
}


def main() -> int:
    OUT.mkdir(exist_ok=True)
    manifest = []
    for slug, src_name, pages, kind in DOCS:
        src = SOURCES[src_name]
        data = BUILDERS[kind](excerpt(fetch(src), pages), slug)
        (OUT / f"{slug}.pdf").write_bytes(data)
        manifest.append(
            {
                "slug": slug,
                "path": f"{slug}.pdf",
                "source": src.url,
                "source_name": src.name,
                "source_pages": pages,
                "kind": kind,
                "watermark_strings": [WATERMARK, FOOTER] if kind == "watermark" else [],
            }
        )
        print(f"{kind:9} {slug:22} {len(pages):3} pages  {len(data) // 1024} KB")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
