import logging
from uuid import UUID

import asyncpg
from eagleeye_core.config import get_settings
from eagleeye_core.envelope import ok
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import CurrentUser
from app.errors import ApiException
from app.repos import chats as chats_repo
from app.repos import documents as docs_repo
from app.repos import messages as messages_repo
from app.repos import runs as runs_repo
from app.repos import usage as usage_repo
from app.services.guards import ensure_enabled, limit_action

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chats", tags=["chats"])

MAX_MESSAGE_CHARS = 8000
MAX_SELECTED_DOCS = 20
STILL_ANSWERING = "Still answering the previous message in this chat."


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class SendMessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    idempotency_key: str = Field(min_length=8, max_length=64)
    doc_ids: list[UUID] = Field(default_factory=list, max_length=MAX_SELECTED_DOCS)


@router.get("")
async def list_chats(request: Request, user: CurrentUser) -> dict:
    rows = await chats_repo.list_chats(request.app.state.pool, user.id)
    return ok([dict(r) for r in rows])


@router.post("", status_code=201)
async def create_chat(request: Request, user: CurrentUser) -> dict:
    row = await chats_repo.create_chat(request.app.state.pool, user.id)
    return ok(dict(row))


@router.get("/{chat_id}")
async def get_chat(chat_id: str, request: Request, user: CurrentUser) -> dict:
    pool = request.app.state.pool
    chat = await chats_repo.get_owned_chat(pool, chat_id, user.id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    rows = await messages_repo.list_messages(pool, chat_id)
    return ok({"chat": dict(chat), "messages": [dict(r) for r in rows]})


@router.patch("/{chat_id}")
async def rename(chat_id: str, body: RenameBody, request: Request, user: CurrentUser) -> dict:
    if not await chats_repo.rename_chat(request.app.state.pool, chat_id, user.id, body.title):
        raise HTTPException(status_code=404, detail="Chat not found")
    return ok({"id": chat_id, "title": body.title})


@router.delete("/{chat_id}")
async def delete(chat_id: str, request: Request, user: CurrentUser) -> dict:
    if not await chats_repo.delete_chat(request.app.state.pool, chat_id, user.id):
        raise HTTPException(status_code=404, detail="Chat not found")
    return ok({"id": chat_id, "deleted": True})


@router.post("/{chat_id}/messages", status_code=202)
async def send_message(
    chat_id: str, body: SendMessageBody, request: Request, user: CurrentUser
) -> dict:
    app = request.app
    pool = app.state.pool
    chat = await chats_repo.get_owned_chat(pool, chat_id, user.id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    duplicate = await messages_repo.find_by_idempotency_key(pool, chat_id, body.idempotency_key)
    if duplicate is not None:
        return ok({"run_id": str(duplicate["run_id"]), "deduplicated": True})
    await ensure_enabled(request, "chat")
    await limit_action(request, user, "messages")

    doc_ids = list(dict.fromkeys(str(d) for d in body.doc_ids))
    if doc_ids:
        visible = await docs_repo.filter_visible_ready(pool, doc_ids, user.id)
        if len(visible) != len(doc_ids):
            raise ApiException(
                422, "VALIDATION_ERROR", "Some selected documents are unavailable or not ready."
            )

    await _admit_run(pool, chat_id, user.id)
    try:
        async with pool.acquire() as conn, conn.transaction():
            run_id = await runs_repo.create_run(conn, chat_id, user.id, {"doc_ids": doc_ids})
            await messages_repo.insert_user_message(
                conn, chat_id, body.text, run_id, body.idempotency_key
            )
    except asyncpg.UniqueViolationError as exc:  # raced another send on this chat
        raise ApiException(409, "CONFLICT", STILL_ANSWERING) from exc

    try:
        await app.state.task_queue.enqueue_run(run_id)
    except Exception as exc:
        logger.exception("could not enqueue run %s", run_id)
        await runs_repo.mark_failed(pool, run_id, "ENQUEUE_FAILED")
        raise ApiException(502, "UPSTREAM_ERROR", "Couldn't start answering. Try again.") from exc
    return ok({"run_id": run_id})


async def _admit_run(pool: asyncpg.Pool, chat_id: str, user_id: str) -> None:
    """One active run per chat, a few per user (C3 §7). Orphaned runs are failed first."""
    await runs_repo.fail_stale_runs(pool, user_id)
    if await runs_repo.has_active_run(pool, chat_id):
        raise ApiException(409, "CONFLICT", STILL_ANSWERING)
    settings = get_settings()
    if await runs_repo.count_active_for_user(pool, user_id) >= settings.max_active_runs_per_user:
        raise ApiException(
            429, "RATE_LIMITED", "Too many answers in progress. Wait for one to finish."
        )
    if await usage_repo.total_cost(pool, user_id) >= settings.usage_limit_usd:
        raise ApiException(
            429,
            "QUOTA_EXCEEDED",
            f"You've reached your ${settings.usage_limit_usd:,.0f} usage limit.",
        )
