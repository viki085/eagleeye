"""Add table questions to the multimodal golden set (one-off, ~USD 0.03).

  .venv/Scripts/python.exe evals/multimodal/build_table_golden.py

build_golden.py asks for "at least one table question per page", which gave only 11 of 150.
This script starts from the tables themselves: each test PDF is parsed (Docling), and for each
table the fast model writes questions answered by ONE cell, naming that cell's row and column.

An answer is kept only if it also appears in the ORIGINAL page's text layer (the source PDF
before it was scanned or watermarked), so a parser that misreads a number cannot make its own
answer key. Questions are appended as t001... with tag "table"; running it again replaces them.
"""

import asyncio
import json
import random
import re
import sys

from build_golden import CORPUS, GOLDEN, norm, page_texts, tag_for
from eagleeye_core.config import get_settings
from eagleeye_llm.env import export_provider_keys
from eagleeye_llm.gateway import ChatMessage
from eagleeye_llm.litellm_adapter import LiteLLMGateway
from ingest_worker import pipeline

TABLES_PER_DOC = 4
PER_TABLE = 3
MAX_TABLE_CHARS = 5000
MIN_TABLE_CHARS = 120  # skip tiny two-cell boxes
PROMPT = """Below is one table (Markdown) from a public report ("{doc}"), page {page}.

Write {n} questions, each answered by exactly ONE cell of this table (a number or a short value).
Each question must name what is needed to find that cell without seeing the table: the measure
(column), the row label (place, year, category) and the report subject. Use different rows.

Reply as JSON: {{"items": [{{"question": "...", "span": "<the cell's exact text>"}}]}}

TABLE:
{table}"""

_FOOTNOTE = re.compile(r"^[a-z] ")  # "e 380": a footnote mark read into the cell


def usable(span: str) -> bool:
    """A checkable answer: has a digit or is a longer phrase, and no stray footnote mark. A bare
    word ("Free") or one digit would match chunks that do not answer the question."""
    text = norm(span)
    if _FOOTNOTE.match(span) or len(text) < 2:
        return False
    return any(ch.isdigit() for ch in text) or len(text.split()) >= 2


async def main() -> int:
    s = get_settings()
    export_provider_keys(s.openai_api_key, s.anthropic_api_key)
    llm = LiteLLMGateway(s.model_fast, s.model_capable, reasoning_fast=s.reasoning_effort_fast)
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    sem = asyncio.Semaphore(6)
    rng = random.Random(7)  # noqa: S311 - a repeatable sample, not security

    async def table_questions(entry: dict, page: int, table: str, original: str) -> list[dict]:
        async with sem:
            raw, _ = await llm.complete(
                "fast",
                [
                    ChatMessage(
                        "user",
                        PROMPT.format(
                            doc=entry["slug"], page=page, n=PER_TABLE, table=table[:MAX_TABLE_CHARS]
                        ),
                    )
                ],
                max_tokens=500,
                json_mode=True,
            )
        try:
            items = json.loads(raw).get("items", [])
        except (ValueError, AttributeError):
            return []
        kept, seen = [], set()
        for item in items:
            span = str(item.get("span", "")).strip().rstrip(".")
            question = str(item.get("question", "")).strip()
            if not question or not usable(span) or norm(span) not in norm(original):
                continue
            if norm(span) in seen:  # several rows with one value test nothing new
                continue
            seen.add(norm(span))
            kept.append(
                {
                    "doc": entry["slug"],
                    "doc_kind": entry["kind"],
                    "page": page,
                    "tag": "table" if tag_for(entry, page, "table") != "scanned" else "scanned",
                    "question": question,
                    "span": span,
                }
            )
        return kept

    jobs = []
    for entry in manifest:
        originals = dict(page_texts(entry))
        parsed = pipeline.parse("pdf", (CORPUS / f"{entry['slug']}.pdf").read_bytes())
        tables = [
            el
            for el in parsed.elements
            if el.kind == "table" and len(el.text) >= MIN_TABLE_CHARS and el.page in originals
        ]
        for el in rng.sample(tables, min(TABLES_PER_DOC, len(tables))):
            jobs.append(table_questions(entry, el.page, el.text, originals[el.page]))
        print(f"{entry['slug']}: {len(tables)} tables")
    new = [r for batch in await asyncio.gather(*jobs) for r in batch]

    kept = [
        line
        for line in GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip() and not json.loads(line)["id"].startswith("t")
    ]
    with GOLDEN.open("w", encoding="utf-8", newline="\n") as f:
        for line in kept:
            f.write(line + "\n")
        for i, r in enumerate(new, start=1):
            f.write(json.dumps({"id": f"t{i:03d}", **r}) + "\n")
    print(f"{len(new)} table questions added -> {GOLDEN} ({len(kept) + len(new)} in all)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
