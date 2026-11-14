import logging
import uuid
from typing import Literal
from uuid import UUID

import asyncpg
from eagleeye_core.config import get_settings
from eagleeye_core.envelope import ok
from eagleeye_core.storage import ObjectNotFoundError
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response

from app.auth import AuthedUser, CurrentUser
from app.errors import ApiException
from app.repos import admin_metrics
from app.repos import documents as docs_repo
from app.services import uploads
from app.services.guards import ensure_enabled, limit_action
from app.services.permissions import can_manage_enterprise

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

PRIVATE_FIELDS = {"s3_key", "sha256"}


def _public(row: asyncpg.Record) -> dict:
    return {k: v for k, v in dict(row).items() if k not in PRIVATE_FIELDS}


def _require_enterprise_manager(user: AuthedUser, action: str) -> None:
    if not can_manage_enterprise(user):
        raise ApiException(
            403, "FORBIDDEN", f"Only knowledge admins can {action} enterprise documents."
        )


async def _audit(
    request: Request, user: AuthedUser, category: str, doc_id: str, title: str
) -> None:
    """Record an enterprise-library change in security_events (title only, never content)."""
    await admin_metrics.record_admin_action(
        request.app.state.pool, user.id, category, {"document_id": doc_id, "title": title}
    )


UPLOAD_FAILED = "Upload could not be processed. Try again."
DELETE_FAILED = "Could not delete right now. Try again."


async def _store_and_enqueue(
    request: Request, doc_id: str, key: str, data: bytes, mime: str
) -> None:
    state = request.app.state
    try:
        await state.store.put(key, data, mime)
        await state.task_queue.enqueue_ingest(doc_id)
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
        _require_enterprise_manager(user, "add")
    await ensure_enabled(request, "uploads")
    await limit_action(request, user, "uploads")
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
    if scope == "enterprise":  # company-wide knowledge: audited before it changes
        await _audit(request, user, "enterprise_doc_added", doc_id, uploads.title_from(filename))
    try:
        row = await docs_repo.insert_document(
            pool,
            doc_id=doc_id,
            scope=scope,
            user_id=user.id,
            title=uploads.title_from(filename),
            filename=filename,
            mime=mime,
            size_bytes=len(payload.data),
            sha256=payload.sha256,
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
    if row["scope"] == "enterprise":
        _require_enterprise_manager(user, "delete")
    elif str(row["uploaded_by"]) != user.id:
        raise ApiException(403, "FORBIDDEN", "Only the uploader can delete this document.")

    if row["scope"] == "enterprise":
        # audit first: if the audit write fails, nothing is deleted unrecorded
        await _audit(request, user, "enterprise_doc_deleted", str(doc_id), row["title"])
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


VIEWABLE_INLINE = {"application/pdf", "text/plain", "text/markdown"}


@router.get("/{doc_id}/file")
async def get_file(doc_id: UUID, request: Request, user: CurrentUser) -> Response:
    """The original file, for the in-app viewer. Same visibility rule as the document itself."""
    state = request.app.state
    row = await docs_repo.get_visible(state.pool, str(doc_id), user.id)
    if row is None:
        raise ApiException(404, "NOT_FOUND", "Document not found.")
    try:
        data = await state.store.get(row["s3_key"])
    except ObjectNotFoundError as exc:
        raise ApiException(404, "NOT_FOUND", "The file is no longer available.") from exc
    mime = row["mime"] if row["mime"] in VIEWABLE_INLINE else "application/octet-stream"
    safe = "".join(ch for ch in row["filename"] if ch.isalnum() or ch in "._- ")[:120] or "document"
    return Response(
        content=data,
        media_type=mime,
        headers={
            "Content-Disposition": f'inline; filename="{safe}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/{doc_id}/text")
async def get_text(doc_id: UUID, request: Request, user: CurrentUser) -> dict:
    """The indexed text in reading order (used to show Word documents in the viewer)."""
    pool = request.app.state.pool
    if await docs_repo.get_visible(pool, str(doc_id), user.id) is None:
        raise ApiException(404, "NOT_FOUND", "Document not found.")
    rows = await docs_repo.list_visible_chunks(pool, str(doc_id), user.id)
    return ok(
        [
            {
                "chunk_no": r["chunk_no"],
                "content": r["content"],
                "heading_path": list(r["heading_path"] or []),
                "page": r["page"],
            }
            for r in rows
        ]
    )
