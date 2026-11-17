"""Multimodal PDF eval scorer: the old pypdf reader vs the shipped Docling parser.

  uv run --package eagleeye-ingest-worker python evals/multimodal/score.py
  uv run --package eagleeye-ingest-worker python evals/multimodal/score.py --parsers docling

Needs the corpus built (build_corpus.py) and the local Supabase running. Each parser goes through
the real pipeline pieces, exactly as an upload would:
  pypdf    PdfParser -> sanitize                      (the parser before Phase 1, no clean step)
  docling  DoclingPdfParser -> sanitize -> clean      (ingest_worker.pipeline.parse, shipped)
then the shipped chunker (tables as their own chunks) -> embedding text -> pgvector + full-text
rows for a temporary eval user -> the real Retriever, query rewriting off. Questions search the
whole corpus, as a user with all 11 documents would. Everything written is deleted at the end.

Parse checks per parser: documents that reach READY (no PermanentIngestError), pages with any
text, table chunks, seconds per page, and chunks still holding a watermark string listed in
corpus/manifest.json. Retrieval (as in evals/retrieval_eval.py): budget_recall (gold span in the
top results cut to the context budget the model reads), recall@5 and MRR, overall and per
question tag and per document kind. Spans are matched loosely (whole words of letters and digits), so a
number that sits in a Markdown table cell still counts: the same rule for both parsers.
Embeddings cost well under $0.01 per parser.
"""

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import asyncpg
from eagleeye_core.config import get_settings
from eagleeye_llm.embeddings import LiteLLMEmbedder
from eagleeye_retrieval.service import Retriever
from eagleeye_retrieval.stores.pgvector_store import PgVectorPersonalStore
from eagleeye_retrieval.types import AccessScope
from ingest_worker import figures, pipeline, repo
from ingest_worker.chunking import Chunk, chunk
from ingest_worker.errors import PermanentIngestError
from ingest_worker.parsing.base import ParsedDocument, sanitize
from ingest_worker.parsing.pdf import PdfParser
from ingest_worker.pipeline import embedding_text

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent))
from retrieval_eval import (  # noqa: E402 — shared eval helpers
    CONTEXT_BUDGET,
    SEPARATOR,
    TOP_N,
    CachingEmbedder,
    NoEnterpriseStore,
)

CORPUS = ROOT / "corpus"
GOLDEN = ROOT / "golden.jsonl"
OUT = ROOT / "out"

PARSERS = {
    "pypdf": lambda data: sanitize(PdfParser().parse(data)),
    "docling": lambda data: pipeline.parse("pdf", data),
}
DESCRIBE = False  # --describe: real figure descriptions (OpenAI vision, about $0.01 per run)


class _MemoryStore:
    async def put(self, key: str, data: bytes, content_type: str) -> None:
        return None


def with_figures(parsed: ParsedDocument, slug: str) -> ParsedDocument:
    """Figures as the pipeline stores them: described (--describe), else caption + printed words,
    which is what a user gets when the vision call fails (a lower bound)."""
    if DESCRIBE:
        # parse_doc runs inside the scorer's event loop: describe in a thread with its own loop
        with ThreadPoolExecutor(1) as pool:
            coro = figures.describe(parsed, _MemoryStore(), f"eval/{slug}")
            return pool.submit(asyncio.run, coro).result()
    elements = tuple(
        replace(
            e,
            text=figures.figure_text("" if e.text == figures.PLACEHOLDER else e.text, "", e.labels),
            image_png=None,
        )
        if e.kind == "image"
        else e
        for e in parsed.elements
    )
    return replace(parsed, elements=elements)


def loose(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def manifest() -> list[dict]:
    return json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))


def _chunks(parsed: ParsedDocument) -> list[Chunk]:
    s = get_settings()
    return chunk(
        parsed.elements,
        max_chars=s.chunk_max_chars,
        soft_chars=s.chunk_soft_chars,
        min_chars=s.chunk_min_chars,
        overlap=s.chunk_overlap_chars,
    )


def watermark_hits(doc: dict, chunks: list[Chunk]) -> int:
    """Chunks that still hold one of the document's watermark strings (as a whole word), in
    their text or their heading path (pypdf reads an ALL CAPS stamp as a heading, which then
    rides along in every following chunk's breadcrumb and embedding text)."""
    patterns = [re.compile(rf"(?<!\w){re.escape(w)}(?!\w)") for w in doc["watermark_strings"]]
    return sum(
        1
        for c in chunks
        if any(p.search(" ".join((*c.heading_path, c.content))) for p in patterns)
    )


def parse_doc(name: str, doc: dict) -> dict:
    data = (CORPUS / doc["path"]).read_bytes()
    pages = len(doc["source_pages"])
    start = time.perf_counter()
    try:
        parsed = with_figures(PARSERS[name](data), doc["slug"])
        chunks = _chunks(parsed)
        error = None if chunks else "no chunks"
    except PermanentIngestError as exc:
        parsed, chunks, error = None, [], exc.user_message
    seconds = time.perf_counter() - start
    text_pages = {e.page for e in parsed.elements if e.page} if parsed else set()
    return {
        "slug": doc["slug"],
        "kind": doc["kind"],
        "ready": error is None,
        "error": error,
        "pages": pages,
        "text_pages": len(text_pages),
        "chunks": chunks,
        "tables": sum(1 for c in chunks if c.element_type == "table"),
        "watermark_chunks": watermark_hits(doc, chunks),
        "s_per_page": round(seconds / pages, 2),
    }


async def ingest(pool: asyncpg.Pool, embedder: CachingEmbedder, docs: list[dict], user: str) -> None:
    async with pool.acquire() as conn:
        for d in docs:
            if not d["chunks"]:
                continue
            vectors = await embedder.embed([embedding_text(d["slug"], c) for c in d["chunks"]])
            row = await conn.fetchrow(
                """
                INSERT INTO documents (scope, owner_id, uploaded_by, title, filename, mime,
                                       size_bytes, sha256, s3_key, status, chunk_count)
                VALUES ('personal', $1, $1, $2, $3, 'application/pdf', 1, $4,
                        'eval/none', 'READY', $5)
                RETURNING id, scope, owner_id
                """,
                user,
                d["slug"],
                f"{d['slug']}.pdf",
                uuid.uuid4().hex,
                len(d["chunks"]),
            )
            async with conn.transaction():
                await repo.replace_chunks(conn, row, d["chunks"], vectors)


def score(span: str, contents: list[str]) -> dict[str, float]:
    target = f" {loose(span)} "  # whole words only: "47" must not match "147"
    rank = next((i for i, c in enumerate(contents) if target in f" {loose(c)} "), None)
    budget_text = f" {loose(SEPARATOR.join(contents)[:CONTEXT_BUDGET])} "
    return {
        "budget_recall": float(target in budget_text),
        "recall@5": float(rank is not None and rank < 5),
        "mrr": 0.0 if rank is None else 1.0 / (rank + 1),
    }


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 3) if values else 0.0


async def evaluate(name: str, questions: list[dict], pool: asyncpg.Pool, embedder) -> dict:  # noqa: ANN001
    docs = [parse_doc(name, d) for d in manifest()]
    user = str(
        await pool.fetchval(
            "INSERT INTO users (clerk_user_id, email) VALUES ($1, $2) RETURNING id",
            f"eval_multimodal_{uuid.uuid4().hex[:8]}",
            f"eval-{uuid.uuid4().hex[:8]}@eval.local",
        )
    )
    try:
        await ingest(pool, embedder, docs, user)
        retriever = Retriever(
            pool,
            llm=None,
            embedder=embedder,
            enterprise_store=NoEnterpriseStore(),
            personal_store=PgVectorPersonalStore(pool),
            top_k=TOP_N,
            min_score=0.0,
        )
        scope = AccessScope(user_id=user, scopes=("personal",))
        overall: dict[str, list[float]] = defaultdict(list)
        by_tag: dict[str, list[float]] = defaultdict(list)
        by_kind: dict[str, list[float]] = defaultdict(list)
        misses = []
        for q in questions:
            result = await retriever.retrieve(q["question"], [], scope, rewrite=False)
            s = score(q["span"], [c.content for c in result.chunks])
            for k, v in s.items():
                overall[k].append(v)
            by_tag[q["tag"]].append(s["budget_recall"])
            by_kind[q["doc_kind"]].append(s["budget_recall"])
            if not s["budget_recall"]:
                misses.append(q["id"])
    finally:
        await pool.execute("DELETE FROM documents WHERE owner_id = $1", user)
        await pool.execute("DELETE FROM users WHERE id = $1", user)
    return {
        "parser": name,
        "ready": sum(d["ready"] for d in docs),
        "docs": len(docs),
        "pages_with_text": sum(d["text_pages"] for d in docs),
        "pages": sum(d["pages"] for d in docs),
        "chunks": sum(len(d["chunks"]) for d in docs),
        "table_chunks": sum(d["tables"] for d in docs),
        "watermark_chunks": sum(d["watermark_chunks"] for d in docs),
        "s_per_page": _mean([d["s_per_page"] for d in docs]),
        **{k: _mean(v) for k, v in overall.items()},
        "budget_recall_by_tag": {k: _mean(v) for k, v in sorted(by_tag.items())},
        "budget_recall_by_kind": {k: _mean(v) for k, v in sorted(by_kind.items())},
        "per_doc": [{k: v for k, v in d.items() if k != "chunks"} for d in docs],
        "misses": misses,
    }


def print_report(results: list[dict], n: int) -> None:
    print(f"\nMultimodal PDF eval ({n} questions), context budget {CONTEXT_BUDGET} chars")
    print(
        f"{'parser':8}{'ready':>7}{'text pages':>12}{'chunks':>8}{'tables':>8}{'watermark':>11}"
        f"{'s/page':>8}{'budget_recall':>15}{'recall@5':>10}{'mrr':>7}"
    )
    for r in results:
        print(
            f"{r['parser']:8}{r['ready']:>4}/{r['docs']:<2}"
            f"{r['pages_with_text']:>8}/{r['pages']:<3}{r['chunks']:>8}{r['table_chunks']:>8}"
            f"{r['watermark_chunks']:>11}{r['s_per_page']:>8}{r['budget_recall']:>15.3f}"
            f"{r['recall@5']:>10.3f}{r['mrr']:>7.3f}"
        )
    for title, key in (("question tag", "budget_recall_by_tag"), ("document kind", "budget_recall_by_kind")):
        keys = sorted({k for r in results for k in r[key]})
        print(f"\nbudget_recall by {title}")
        print(f"{'parser':8}" + "".join(f"{k:>11}" for k in keys))
        for r in results:
            print(f"{r['parser']:8}" + "".join(f"{r[key].get(k, 0):>11.3f}" for k in keys))
    print("\nper document (ready, pages with text / pages, table chunks, watermark chunks)")
    for r in results:
        cells = [
            f"{d['slug']}:{'ok' if d['ready'] else 'FAIL'} {d['text_pages']}/{d['pages']}"
            f" t{d['tables']} w{d['watermark_chunks']}"
            for d in r["per_doc"]
        ]
        print(f"{r['parser']:8}" + " | ".join(cells))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parsers", default="pypdf,docling")
    ap.add_argument("--json", type=Path, default=OUT / "scores.json")
    ap.add_argument("--describe", action="store_true", help="real figure descriptions (~$0.01)")
    args = ap.parse_args()
    global DESCRIBE
    DESCRIBE = args.describe
    if not any(CORPUS.glob("*.pdf")):
        sys.exit("No corpus PDFs: run evals/multimodal/build_corpus.py first.")
    questions = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines()]
    s = get_settings()
    embedder = CachingEmbedder(LiteLLMEmbedder(s.embed_model, s.embed_dim))
    pool = await asyncpg.create_pool(s.database_url, min_size=1, max_size=4)
    try:
        results = [await evaluate(p, questions, pool, embedder) for p in args.parsers.split(",")]
    finally:
        await pool.close()
    print_report(results, len(questions))
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
