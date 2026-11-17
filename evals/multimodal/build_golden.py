"""Build the multimodal golden questions from the test set's source pages (one-off, ~USD 0.05).

  .venv/Scripts/python.exe evals/multimodal/build_golden.py

For each content page of each test document, the fast model reads the ORIGINAL page's text layer
(before it was scanned, watermarked or turned into a slide image) and writes questions with a
short verbatim answer span, saying whether the answer sits in a table. A span is kept only if it
appears in that page's text, so every question has a checkable answer and a known page.

Tag per question (what makes it hard):
  scanned  the page has no text layer in the test copy (scanned docs, first pages of "mixed")
  image    the page is a picture in a slide deck
  table    the answer is in a table
  text     the answer is in running text
Documents with a watermark keep their table/text tag; the eval reports them by kind as well.
"""

import asyncio
import json
import re
import sys
from pathlib import Path

from eagleeye_core.config import get_settings
from eagleeye_llm.env import export_provider_keys
from eagleeye_llm.gateway import ChatMessage
from eagleeye_llm.litellm_adapter import LiteLLMGateway
from pypdf import PdfReader

ROOT = Path(__file__).parent
CORPUS = ROOT / "corpus"
PDFS = ROOT / "pdfs"
GOLDEN = ROOT / "golden.jsonl"
MIN_PAGE_CHARS = 600  # skip covers, tables of contents and other near-empty pages
MAX_PAGE_CHARS = 6000
PER_PAGE = 2
MIXED_RASTER_PAGES = 3  # keep in step with build_corpus.py
PROMPT = """Below is the text of one page from a public report ("{doc}").

Write {n} questions an analyst might ask that this page answers. Prefer specific facts: numbers,
dates, names. At least one should be answered by a value in a table, if the page has a table.
Word each question so it has exactly one answer without seeing the page (name the measure, the
year, the place). For each, give the shortest exact substring of the page text that answers it
(1 to 8 words, usually a number with its unit), and whether that answer is in a "table" or in
running "text".

Reply as JSON: {{"items": [{{"question": "...", "span": "...", "where": "table" | "text"}}]}}

PAGE TEXT:
{text}"""


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(",", "")).strip().lower()


def page_texts(entry: dict) -> list[tuple[int, str]]:
    """(page number in the test copy, original text) for the document's source pages."""
    src = PdfReader(PDFS / f"{entry['source_name']}.pdf")
    return [
        (i, src.pages[p - 1].extract_text() or "")
        for i, p in enumerate(entry["source_pages"], start=1)
        if p <= len(src.pages)
    ]


def tag_for(entry: dict, page: int, where: str) -> str:
    if entry["kind"] == "scanned" or (entry["kind"] == "mixed" and page <= MIXED_RASTER_PAGES):
        return "scanned"
    if entry["kind"] == "deck":
        return "image"
    return "table" if where == "table" else "text"


async def main() -> int:
    s = get_settings()
    export_provider_keys(s.openai_api_key, s.anthropic_api_key)
    llm = LiteLLMGateway(s.model_fast, s.model_capable, reasoning_fast=s.reasoning_effort_fast)
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    sem = asyncio.Semaphore(6)

    async def page_questions(entry: dict, page: int, text: str) -> list[dict]:
        async with sem:
            raw, _ = await llm.complete("fast", [ChatMessage("user", PROMPT.format(
                doc=entry["slug"], n=PER_PAGE, text=text[:MAX_PAGE_CHARS]))],
                max_tokens=600, json_mode=True)
        try:
            items = json.loads(raw).get("items", [])
        except (ValueError, AttributeError):
            return []
        kept = []
        for item in items:
            span = str(item.get("span", "")).strip().rstrip(".")
            question = str(item.get("question", "")).strip()
            if span and question and norm(span) in norm(text):
                kept.append({"doc": entry["slug"], "doc_kind": entry["kind"], "page": page,
                             "tag": tag_for(entry, page, str(item.get("where", ""))),
                             "question": question, "span": span})
        return kept

    jobs = [page_questions(e, page, text)
            for e in manifest
            for page, text in page_texts(e)
            if len(text.strip()) >= MIN_PAGE_CHARS]
    rows = [r for batch in await asyncio.gather(*jobs) for r in batch]
    with GOLDEN.open("w", encoding="utf-8", newline="\n") as f:
        for i, r in enumerate(rows, start=1):
            f.write(json.dumps({"id": f"m{i:03d}", **r}) + "\n")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["tag"]] = counts.get(r["tag"], 0) + 1
    print(f"{len(rows)} questions -> {GOLDEN}  by tag: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
