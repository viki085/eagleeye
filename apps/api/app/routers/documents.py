import logging
import uuid
from typing import Literal
from uuid import UUID

import asyncpg
from eagleeye_core.config import get_settings
from eagleeye_core.envelope import ok
from fastapi import APIRouter, File, Form, Request, UploadFile

from app.auth import AuthedUser, CurrentUser
from app.errors import ApiException
from app.repos import documents as docs_repo
from app.services import uploads

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

ENTERPRISE_UPLOAD_ROLES = {"knowledge_admin", "admin"}
PRIVATE_FIELDS = {"s3_key", "sha256"}


def _public(row: asyncpg.Record) -> dict:
    return {k: v for k, v in dict(row).items() if k not in PRIVATE_FIELDS}


def _require_enterprise_upload(user: AuthedUser) -> None:
    if get_settings().enterprise_upload_open or user.role in ENTERPRISE_UPLOAD_ROLES:
        return
    raise ApiException(403, "FORBIDDEN", "Only knowledge admins can add enterprise documents.")


UPLOAD_FAILED = "Upload could not be processed. Try again."
DELETE_FAILED = "Could not delete right now. Try again."


async def _store_and_enqueue(
    request: Request, doc_id: str, key: str, data: bytes, mime: str
) -> None:
    state = request.app.state
    try:
        await state.store.put(key, data, mime)
        await state.ingest_queue.enqueue(doc_id)
    except Exception as exc:
        logger.exception("upload %s: storing or enqueueing failed", doc_id)
        await docs_repo.mark_failed(state.pool, doc_id, UPLOAD_FAILED)
        raise ApiException(502, "UPSTREAM_ERROR", UPLOAD_FAILED) from exc


@router.post("", status_code=201)
async def upload_document(
    request: Request,
    user: CurrentUser,
    file: UploadFile = File(...),  # noqa: B008 - FastAPI dependency marker
    scope: Literal["personal", "enterprise"] = Form("personal"),
) -> dict:
    if scope == "enterprise":
        _require_enterprise_upload(user)
    filename = uploads.safe_filename(file.filename)
    ext, mime = uploads.require_supported(filename)
    payload = await uploads.read_limited(file, get_settings().max_upload_mb * 1024 * 1024)

    pool = request.app.state.pool
    duplicate = await docs_repo.find_duplicate(pool, payload.sha256, scope, user.id)
    if duplicate is not None:
        title = duplicate["title"]
        raise ApiException(409, "CONFLICT", f'This file was already uploaded as "{title}".')

    doc_id = str(uuid.uuid4())
    key = uploads.object_key(scope, doc_id, ext)
    try:
        row = await docs_repo.insert_document(
            pool, doc_id=doc_id, scope=scope, user_id=user.id, title=uploads.title_from(filename),
            filename=filename, mime=mime, size_bytes=len(payload.data), sha256=payload.sha256,
            s3_key=key,
        )
    except asyncpg.UniqueViolationError as exc:  # concurrent duplicate upload
        raise ApiException(409, "CONFLICT", "This file was already uploaded.") from exc

    await _store_and_enqueue(request, doc_id, key, payload.data, mime)
    return ok(_public(row))


@router.get("")
async def list_documents(request: Request, user: CurrentUser) -> dict:
    rows = await docs_repo.list_visible(request.app.state.pool, user.id)
    return ok([_public(r) for r in rows])


@router.get("/{doc_id}")
async def get_document(doc_id: UUID, request: Request, user: CurrentUser) -> dict:
    row = await docs_repo.get_visible(request.app.state.pool, str(doc_id), user.id)
    if row is None:
        raise ApiException(404, "NOT_FOUND", "Document not found.")
    return ok(_public(row))


@router.delete("/{doc_id}")
async def delete_document(doc_id: UUID, request: Request, user: CurrentUser) -> dict:
    state = request.app.state
    row = await docs_repo.get_visible(state.pool, str(doc_id), user.id)
    if row is None:
        raise ApiException(404, "NOT_FOUND", "Document not found.")
    if str(row["uploaded_by"]) != user.id:
        raise ApiException(403, "FORBIDDEN", "Only the uploader can delete this document.")

    if row["scope"] == "enterprise":
        try:
            await state.enterprise_store.delete_document(str(doc_id))
        except Exception as exc:
            logger.exception("delete %s: vector store cleanup failed", doc_id)
            raise ApiException(502, "UPSTREAM_ERROR", DELETE_FAILED) from exc
    await docs_repo.delete_document(state.pool, str(doc_id))
    try:
        await state.store.delete(row["s3_key"])
    except Exception:
        logger.warning("delete %s: object %s not removed", doc_id, row["s3_key"], exc_info=True)
    return ok({"id": str(doc_id), "deleted": True})


@router.get("/{doc_id}/chunks/{chunk_id}")
async def get_chunk(doc_id: UUID, chunk_id: UUID, request: Request, user: CurrentUser) -> dict:
    row = await docs_repo.get_visible_chunk(
        request.app.state.pool, str(doc_id), str(chunk_id), user.id
    )
    if row is None:
        raise ApiException(404, "NOT_FOUND", "Source not found.")
    return ok(
        {
            "id": str(row["id"]),
            "chunk_no": row["chunk_no"],
            "content": row["content"],
            "heading_path": list(row["heading_path"] or []),
            "page": row["page"],
            "document": {"id": str(row["document_id"]), "title": row["title"]},
        }
    )
