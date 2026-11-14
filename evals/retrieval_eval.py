"""Retrieval eval: compares chunking configurations on the Grand Line corpus (C4, ADR-32).

  uv run --package eagleeye-ingest-worker python evals/retrieval_eval.py            # dev split
  uv run --package eagleeye-ingest-worker python evals/retrieval_eval.py --split test --configs C

Uses the real pipeline pieces: parser -> chunker -> embedding text -> pgvector + full-text
rows (as a temporary eval user's personal documents) -> the real Retriever with query rewriting
off (deterministic). Everything the eval writes is deleted at the end.

Metrics, per configuration (overall and per document kind):
  budget_recall  gold span inside the top results cut to CONTEXT_BUDGET characters, i.e. what
                 the model would actually read. Fair across chunk sizes: five huge chunks don't
                 win just by containing more text.
  recall@5       gold span in any of the top 5 chunks (as hydrated: truncated like production)
  mrr            1 / rank of the first chunk containing the span (0 beyond the top 20)
Embeddings cost about $0.10 per configuration (about 400 documents).
"""

import argparse
import asyncio
import hashlib
import json
import re
import statistics
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import asyncpg
from eagleeye_core.config import get_settings
from eagleeye_llm.embeddings import LiteLLMEmbedder
from eagleeye_retrieval.service import Retriever
from eagleeye_retrieval.stores.pgvector_store import PgVectorPersonalStore
from eagleeye_retrieval.types import AccessScope, VectorHit
from ingest_worker import repo
from ingest_worker.chunking import chunk
from ingest_worker.parsing.base import sanitize
from ingest_worker.parsing.pdf import PdfOptions, PdfParser
from ingest_worker.parsing.registry import parser_for
from ingest_worker.pipeline import embedding_text
from ingest_worker.sniff import sniff

ROOT = Path(__file__).parent
CORPUS = ROOT.parent / "data" / "grandline" / "out"  # built by data/grandline/make_docs.py
GOLDEN = ROOT / "retrieval_golden.jsonl"  # built by evals/build_retrieval_golden.py


def corpus() -> list[tuple[Path, str, str]]:
    """(file, slug, title) for every document in the Grand Line library."""
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    return [(CORPUS / d["path"], d["slug"], d["title"]) for d in manifest]
CONTEXT_BUDGET = 6000
TOP_N = 20
SEPARATOR = " ¦ "  # between chunks, so a span can't match across a chunk boundary


@dataclass(frozen=True)
class Config:
    name: str
    description: str
    max_chars: int
    soft_chars: int
    min_chars: int
    overlap: int
    pdf: PdfOptions


CONFIGS = {
    "A": Config("A", "current: 2400/3000, overlap 300", 3000, 2400, 600, 300, PdfOptions()),
    "B": Config("B", "smaller: 1200/1600, overlap 200", 1600, 1200, 400, 200, PdfOptions()),
    "C": Config(
        "C",
        "B + PDF slide markers and bullets",
        1600,
        1200,
        400,
        200,
        PdfOptions(slide_markers=True, bullets=True),
    ),
    "D": Config(
        "D",
        "C + Title Case headings",
        1600,
        1200,
        400,
        200,
        PdfOptions(slide_markers=True, bullets=True, title_case_headings=True),
    ),
}


class CachingEmbedder:
    """Each distinct text is embedded once per run (questions repeat across configs)."""

    def __init__(self, inner: LiteLLMEmbedder) -> None:
        self._inner = inner
        self._cache: dict[str, list[float]] = {}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        keys = [hashlib.sha256(t.encode()).hexdigest() for t in texts]
        missing = list(
            dict.fromkeys(t for t, k in zip(texts, keys, strict=True) if k not in self._cache)
        )
        if missing:
            for text, vec in zip(missing, await self._inner.embed(missing), strict=True):
                self._cache[hashlib.sha256(text.encode()).hexdigest()] = vec
        return [self._cache[k] for k in keys]


class NoEnterpriseStore:
    async def search(self, vector: list[float], scope: AccessScope, limit: int) -> list[VectorHit]:
        return []


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def parse(path: Path, cfg: Config):  # noqa: ANN201
    data = path.read_bytes()
    kind = sniff(path.name, data)
    parser = PdfParser(cfg.pdf) if kind == "pdf" else parser_for(kind)
    return sanitize(parser.parse(data))


async def ingest(pool: asyncpg.Pool, embedder: CachingEmbedder, cfg: Config, user: str) -> dict:
    sizes: list[int] = []
    per_doc: dict[str, int] = {}
    async with pool.acquire() as conn:
        for path, slug, title in corpus():
            chunks = chunk(
                parse(path, cfg).elements,
                max_chars=cfg.max_chars,
                soft_chars=cfg.soft_chars,
                min_chars=cfg.min_chars,
                overlap=cfg.overlap,
            )
            vectors = await embedder.embed([embedding_text(title, c) for c in chunks])
            doc = await conn.fetchrow(
                """
                INSERT INTO documents (scope, owner_id, uploaded_by, title, filename, mime,
                                       size_bytes, sha256, s3_key, status, chunk_count)
                VALUES ('personal', $1, $1, $2, $3, 'application/octet-stream', $4, $5,
                        'eval/none', 'READY', $6)
                RETURNING id, scope, owner_id
                """,
                user,
                title,
                path.name,
                path.stat().st_size,
                uuid.uuid4().hex,
                len(chunks),
            )
            async with conn.transaction():
                await repo.replace_chunks(conn, doc, chunks, vectors)
            sizes += [len(c.content) for c in chunks]
            per_doc[slug] = len(chunks)
    return {
        "chunks": sum(per_doc.values()),
        "avg_chars": round(statistics.mean(sizes)),
        "max_chars": max(sizes),
        "chunks_per_doc": round(sum(per_doc.values()) / len(per_doc), 1),
    }


def score(span: str, contents: list[str]) -> dict[str, float]:
    target = norm(span)
    rank = next((i for i, c in enumerate(contents) if target in norm(c)), None)
    budget_text = norm(SEPARATOR.join(contents))[:CONTEXT_BUDGET]
    return {
        "budget_recall": float(target in budget_text),
        "recall@5": float(rank is not None and rank < 5),
        "mrr": 0.0 if rank is None else 1.0 / (rank + 1),
    }


async def evaluate(
    cfg: Config, questions: list[dict], pool: asyncpg.Pool, embedder: CachingEmbedder
) -> dict:
    user = str(
        await pool.fetchval(
            "INSERT INTO users (clerk_user_id, email) VALUES ($1, $2) RETURNING id",
            f"eval_retrieval_{uuid.uuid4().hex[:8]}",
            f"eval-{uuid.uuid4().hex[:8]}@eval.local",
        )
    )
    try:
        stats = await ingest(pool, embedder, cfg, user)
        retriever = Retriever(
            pool,
            llm=None,
            embedder=embedder,  # type: ignore[arg-type]
            enterprise_store=NoEnterpriseStore(),
            personal_store=PgVectorPersonalStore(pool),
            top_k=TOP_N,
            min_score=0.0,
        )
        scope = AccessScope(user_id=user, scopes=("personal",))
        overall: dict[str, list[float]] = defaultdict(list)
        by_kind: dict[str, list[float]] = defaultdict(list)
        misses = []
        for q in questions:
            result = await retriever.retrieve(q["question"], [], scope, rewrite=False)
            s = score(q["span"], [c.content for c in result.chunks])
            for k, v in s.items():
                overall[k].append(v)
            by_kind[q["kind"]].append(s["budget_recall"])
            if not s["budget_recall"]:
                misses.append(q["id"])
        return {
            "config": cfg.name,
            "description": cfg.description,
            **stats,
            **{k: round(statistics.mean(v), 3) for k, v in overall.items()},
            "budget_recall_by_kind": {
                k: round(statistics.mean(v), 3) for k, v in sorted(by_kind.items())
            },
            "misses": misses,
        }
    finally:
        await pool.execute("DELETE FROM documents WHERE owner_id = $1", user)
        await pool.execute("DELETE FROM users WHERE id = $1", user)


def print_table(results: list[dict], split: str, n: int) -> None:
    print(
        f"\nRetrieval eval - split={split} ({n} questions), context budget {CONTEXT_BUDGET} chars"
    )
    print(
        f"{'cfg':4}{'budget_recall':>14}{'recall@5':>10}{'mrr':>7}{'chunks':>8}"
        f"{'per_doc':>8}{'avg_chars':>10}{'max_chars':>10}  description"
    )
    for r in results:
        print(
            f"{r['config']:4}{r['budget_recall']:>14.3f}{r['recall@5']:>10.3f}{r['mrr']:>7.3f}"
            f"{r['chunks']:>8}{r['chunks_per_doc']:>8}{r['avg_chars']:>10}{r['max_chars']:>10}"
            f"  {r['description']}"
        )
    kinds = sorted({k for r in results for k in r["budget_recall_by_kind"]})
    print("\nbudget_recall by document kind")
    print(f"{'cfg':4}" + "".join(f"{k:>15}" for k in kinds))
    for r in results:
        print(
            f"{r['config']:4}"
            + "".join(f"{r['budget_recall_by_kind'].get(k, 0):>15.3f}" for k in kinds)
        )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="A,B,C,D")
    ap.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    ap.add_argument("--json", type=Path, help="also write results here")
    args = ap.parse_args()
    questions = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines()]
    if args.split != "all":
        questions = [q for q in questions if q["split"] == args.split]
    s = get_settings()
    embedder = CachingEmbedder(LiteLLMEmbedder(s.embed_model, s.embed_dim))
    pool = await asyncpg.create_pool(s.database_url, min_size=1, max_size=4)
    try:
        results = [
            await evaluate(CONFIGS[c], questions, pool, embedder) for c in args.configs.split(",")
        ]
    finally:
        await pool.close()
    print_table(results, args.split, len(questions))
    if args.json:
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
