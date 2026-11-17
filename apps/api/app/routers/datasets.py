"""Data files (CSV/TSV/XLSX) for analysis: upload, list, profile, rows, delete. Owner-only.

Files live in the documents bucket under `datasets/{owner}/{id}/`; the ingest worker turns
them into Parquet + a profile. Another user's dataset id always returns 404.
"""

import hashlib
import logging
import uuid
from typing import Any
from uuid import UUID

from eagleeye_core.config import get_settings
from eagleeye_core.envelope import ok
from eagleeye_core.storage import ObjectNotFoundError
from eagleeye_datasets.models import Dataset, original_key
from eagleeye_datasets.repo import DatasetRepo
from fastapi import APIRouter, File, Query, Request, UploadFile
from pydantic import BaseModel

from app.auth import AuthedUser, CurrentUser
from app.errors import ApiException
from app.repos import documents as docs_repo
from app.services import artifact_reader, uploads
from app.services.guards import ensure_enabled, limit_action
from app.services.table_csv import TableParseError, to_csv

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/datasets", tags=["datasets"])

DATA_EXTENSIONS = {
    ".csv": ("csv_upload", "text/csv"),
    ".tsv": ("csv_upload", "text/tab-separated-values"),
    ".xlsx": (
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
}
MAX_PAGE = 200
UPLOAD_FAILED = "Upload could not be processed. Try again."


def _public(ds: Dataset, with_profile: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": ds.id,
        "title": ds.title,
        "filename": ds.filename,
        "sheet": ds.sheet,
        "origin": ds.origin,
        "status": ds.status,
        "error": ds.error,
        "row_count": ds.row_count,
        "column_count": len(ds.columns),
        "columns": list(ds.columns),
        "size_bytes": ds.size_bytes,
        "summary": ds.summary,
        "created_at": ds.created_at.isoformat() if ds.created_at else None,
    }
    if with_profile:
        out["profile"] = ds.profile
        out["column_map"] = ds.column_map
    return out


def _repo(request: Request) -> DatasetRepo:
    return DatasetRepo(request.app.state.pool)


async def _owned(request: Request, dataset_id: UUID, user_id: str) -> Dataset:
    ds = await _repo(request).get(str(dataset_id), user_id)
    if ds is None:
        raise ApiException(404, "NOT_FOUND", "Data file not found.")
    return ds


def _require_data_file(filename: str) -> tuple[str, str, str]:
    ext = uploads.extension_of(filename)
    if ext not in DATA_EXTENSIONS:
        allowed = ", ".join(sorted(DATA_EXTENSIONS))
        raise ApiException(
            415, "UNSUPPORTED_MEDIA_TYPE", f"Unsupported file type. Allowed: {allowed}"
        )
    origin, mime = DATA_EXTENSIONS[ext]
    return ext, origin, mime


@router.post("", status_code=201)
async def upload_dataset(
    request: Request,
    user: CurrentUser,
    file: UploadFile = File(...),  # noqa: B008 - FastAPI dependency marker
) -> dict:
    await ensure_enabled(request, "uploads")
    await limit_action(request, user, "uploads")
    filename = uploads.safe_filename(file.filename)
    _require_data_file(filename)  # refuse an unsupported type before reading the body
    payload = await uploads.read_limited(file, get_settings().max_upload_mb * 1024 * 1024)
    duplicate = await _duplicate(request, user.id, payload.sha256)
    if duplicate is not None:
        raise ApiException(
            409, "CONFLICT", f'This file was already uploaded as "{duplicate.title}".'
        )
    ds = await _store_new(
        request, user, payload.data, payload.sha256, filename, uploads.title_from(filename)
    )
    return ok(_public(ds))


async def _duplicate(request: Request, user_id: str, sha256: str) -> Dataset | None:
    dataset_id = await request.app.state.pool.fetchval(
        "SELECT id FROM datasets WHERE owner_id = $1 AND sha256 = $2 LIMIT 1", user_id, sha256
    )
    return None if dataset_id is None else await _repo(request).get(str(dataset_id), user_id)


async def _store_new(
    request: Request, user: AuthedUser, data: bytes, sha256: str, filename: str, title: str
) -> Dataset:
    """Record, store and queue a new data file (the worker turns it into Parquet + a profile)."""
    ext, origin, mime = _require_data_file(filename)
    state, repo = request.app.state, _repo(request)
    dataset_id = str(uuid.uuid4())
    key = original_key(user.id, dataset_id, ext)
    created = await repo.create(
        dataset_id=dataset_id,
        owner_id=user.id,
        origin=origin,
        title=title,
        filename=filename,
        sheet="",
        s3_key_original=key,
        size_bytes=len(data),
        sha256=sha256,
    )
    if not created:  # concurrent duplicate upload
        raise ApiException(409, "CONFLICT", "This file was already uploaded.")
    try:
        await state.store.put(key, data, mime)
        await state.task_queue.enqueue_dataset(dataset_id)
    except Exception as exc:
        logger.exception("dataset upload %s: storing or enqueueing failed", dataset_id)
        await repo.set_status(dataset_id, "FAILED", UPLOAD_FAILED)
        raise ApiException(502, "UPSTREAM_ERROR", UPLOAD_FAILED) from exc
    ds = await repo.get(dataset_id, user.id)
    if ds is None:  # deleted in between; treat as gone
        raise ApiException(404, "NOT_FOUND", "Data file not found.")
    return ds


class FromTable(BaseModel):
    document_id: UUID
    chunk_id: UUID


@router.post("/from-table", status_code=201)
async def dataset_from_table(body: FromTable, request: Request, user: CurrentUser) -> dict:
    """A cited table as a data file ("Use as data file" in the source panel). Same visibility
    rule as the source itself; saving the same table again returns the existing data file."""
    await ensure_enabled(request, "uploads")
    row = await docs_repo.get_visible_chunk(
        request.app.state.pool, str(body.document_id), str(body.chunk_id), user.id
    )
    if row is None or row["element_type"] != "table":
        raise ApiException(404, "NOT_FOUND", "Table not found.")
    try:
        data = to_csv(row.get("table_html"), row["content"])
    except TableParseError as exc:
        raise ApiException(422, "VALIDATION_ERROR", "This table could not be read.") from exc
    sha256 = hashlib.sha256(data).hexdigest()
    existing = await _duplicate(request, user.id, sha256)
    if existing is not None:
        return ok(_public(existing) | {"existing": True})
    await limit_action(request, user, "uploads")
    page = f" p{row['page']}" if row.get("page") is not None else ""
    title = f"{row['title']} — table{page}"[:200]
    filename = uploads.safe_filename(f"{row['title'][:80]} table{page}.csv")
    ds = await _store_new(request, user, data, sha256, filename, title)
    return ok(_public(ds) | {"existing": False})


@router.get("")
async def list_datasets(request: Request, user: CurrentUser) -> dict:
    return ok([_public(d) for d in await _repo(request).list_for(user.id)])


@router.get("/{dataset_id}")
async def get_dataset(dataset_id: UUID, request: Request, user: CurrentUser) -> dict:
    return ok(_public(await _owned(request, dataset_id, user.id), with_profile=True))


@router.get("/{dataset_id}/rows")
async def get_rows(
    dataset_id: UUID,
    request: Request,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=MAX_PAGE),
) -> dict:
    ds = await _owned(request, dataset_id, user.id)
    if ds.status != "READY" or not ds.s3_key:
        raise ApiException(409, "CONFLICT", "This file is still being processed.")
    try:
        data = await request.app.state.store.get(ds.s3_key)
    except ObjectNotFoundError as exc:
        raise ApiException(404, "NOT_FOUND", "The file's data is no longer available.") from exc
    page = artifact_reader.page(artifact_reader.read_table(data), offset, limit)
    return ok({"columns": page.columns, "rows": page.rows, "offset": offset, "total": page.total})


@router.delete("/{dataset_id}")
async def delete_dataset(dataset_id: UUID, request: Request, user: CurrentUser) -> dict:
    state = request.app.state
    ds = await _owned(request, dataset_id, user.id)
    shared = await state.pool.fetchval(
        "SELECT 1 FROM datasets WHERE s3_key = $1 AND id <> $2 LIMIT 1", ds.s3_key, ds.id
    )
    if user.is_demo and shared:
        raise ApiException(403, "FORBIDDEN", "The sample files can't be deleted in the demo.")
    await _repo(request).delete(ds.id, user.id)
    still_used = await state.pool.fetchval(
        "SELECT 1 FROM datasets WHERE s3_key_original = $1 LIMIT 1", ds.s3_key_original
    )
    # another row may point at the same processed data (demo visits share the sample files)
    keys = [ds.s3_key] if ds.s3_key and not shared else []
    if not still_used:  # other sheets of the same workbook keep the original
        keys.append(ds.s3_key_original)
    for key in keys:
        try:
            await state.store.delete(key)
        except Exception:
            logger.warning("dataset delete %s: object %s not removed", ds.id, key, exc_info=True)
    return ok({"id": ds.id, "deleted": True})
