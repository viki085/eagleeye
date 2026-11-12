"""Decide whether (and with what) to ground an answer in documents.

Phase 2 has no router yet (Phase 3), so the rule is:
- user selected documents          → always grounded on those (empty context → "not covered")
- no selection, user has READY docs → retrieve across everything visible; ground only when
                                      relevance clears RAG_MIN_SCORE, else plain chat
- no documents                      → plain chat
Retrieval failures degrade to plain chat; they never fail the run.
"""

import logging
from dataclasses import dataclass

import asyncpg
from eagleeye_llm.gateway import ChatMessage
from eagleeye_retrieval.service import Retriever
from eagleeye_retrieval.types import AccessScope, RetrievedChunk

from app.events import EventSink
from app.repos import documents as docs_repo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Grounding:
    chunks: tuple[RetrievedChunk, ...]
    explicit: bool  # user narrowed to specific documents


async def ground(
    pool: asyncpg.Pool,
    retriever: Retriever | None,
    sink: EventSink,
    question: str,
    prior: list[ChatMessage],
    user_id: str,
    doc_ids: list[str],
) -> Grounding | None:
    if retriever is None or not question.strip():
        return None
    if not doc_ids and await docs_repo.count_ready_visible(pool, user_id) == 0:
        return None

    await sink.emit("status", {"stage": "retrieving"})
    scope = AccessScope(user_id=user_id, doc_ids=tuple(doc_ids) or None)
    try:
        result = await retriever.retrieve(question, prior, scope)
    except Exception:
        logger.warning("retrieval failed; answering without documents", exc_info=True)
        return None

    if doc_ids:
        return Grounding(result.chunks, explicit=True)
    if result.low_relevance:
        return None
    return Grounding(result.chunks, explicit=False)
