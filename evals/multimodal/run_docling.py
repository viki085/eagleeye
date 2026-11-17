"""Runs Docling over the multimodal test set and records what it extracts (Phase 0).

  evals/multimodal/.venv/Scripts/python.exe evals/multimodal/run_docling.py [--describe] [--ocr auto|rapidocr|easyocr|tesseract]

Writes out/docling[-<variant>]/<slug>.md (body text as Markdown), <slug>.json (the full
DoclingDocument), figure PNGs, and summary.json: per document pages, seconds, tables, pictures by
class, and watermark strings that leaked into the body text. Everything runs locally.
"""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    OcrAutoOptions,
    PdfPipelineOptions,
    RapidOcrOptions,
    TesseractOcrOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption

ROOT = Path(__file__).parent
CORPUS = ROOT / "corpus"
OCR = {
    "auto": OcrAutoOptions,
    "rapidocr": RapidOcrOptions,
    "easyocr": EasyOcrOptions,
    "tesseract": TesseractOcrOptions,
}
IMAGES_SCALE = 2.0


def make_converter(ocr: str, describe: bool) -> DocumentConverter:
    opts = PdfPipelineOptions(
        do_ocr=True,
        ocr_options=OCR[ocr](),
        do_table_structure=True,
        do_picture_classification=True,
        do_picture_description=describe,
        generate_picture_images=True,
        images_scale=IMAGES_SCALE,
    )
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def picture_classes(doc) -> Counter:
    counts: Counter = Counter()
    for pic in doc.pictures:
        label = "unclassified"
        for ann in getattr(pic, "annotations", []) or []:
            classes = getattr(ann, "predicted_classes", None)
            if classes:
                label = classes[0].class_name
        counts[label] += 1
    return counts


def save_figures(doc, out: Path, slug: str) -> int:
    saved = 0
    for i, pic in enumerate(doc.pictures):
        img = pic.get_image(doc)
        if img is not None:
            img.save(out / f"{slug}_fig{i:02d}.png")
            saved += 1
    return saved


def parse_one(converter: DocumentConverter, entry: dict, out: Path) -> dict:
    started = time.perf_counter()
    result = converter.convert(CORPUS / entry["path"])
    seconds = time.perf_counter() - started
    doc = result.document
    md = doc.export_to_markdown()
    (out / f"{entry['slug']}.md").write_text(md, encoding="utf-8")
    (out / f"{entry['slug']}.json").write_text(json.dumps(doc.export_to_dict()), encoding="utf-8")
    pages = len(doc.pages)
    return {
        "slug": entry["slug"],
        "kind": entry["kind"],
        "status": str(result.status),
        "pages": pages,
        "seconds": round(seconds, 1),
        "seconds_per_page": round(seconds / max(pages, 1), 2),
        "chars": len(md),
        "tables": len(doc.tables),
        "pictures": dict(picture_classes(doc)),
        "figures_saved": save_figures(doc, out, entry["slug"]),
        "watermark_hits": {s: md.count(s) for s in entry["watermark_strings"]},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--describe", action="store_true", help="add local picture descriptions")
    ap.add_argument("--ocr", choices=sorted(OCR), default="auto")
    ap.add_argument("--only", nargs="*", help="slugs to run (default: all)")
    args = ap.parse_args()

    variant = "docling" + ("" if args.ocr == "auto" else f"-{args.ocr}") + ("-describe" if args.describe else "")
    out = ROOT / "out" / variant
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    entries = [e for e in manifest if not args.only or e["slug"] in args.only]

    converter = make_converter(args.ocr, args.describe)
    rows = []
    for entry in entries:
        try:
            row = parse_one(converter, entry, out)
        except Exception as exc:  # report the failure and keep going: this is a measurement run
            row = {"slug": entry["slug"], "kind": entry["kind"], "status": "ERROR", "error": repr(exc)[:300]}
        rows.append(row)
        print(json.dumps(row), flush=True)
    (out / "summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
