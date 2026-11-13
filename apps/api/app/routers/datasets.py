"""Data files (CSV/TSV/XLSX) for analysis: upload, list, profile, rows, delete. Owner-only.

Files live in the documents bucket under `datasets/{owner}/{id}/`; the ingest worker turns
them into Parquet + a profile. Another user's dataset id always returns 404.
"""

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

from app.auth import CurrentUser
from app.errors import ApiException
from app.services import artifact_reader, uploads

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
    filename = uploads.safe_filename(file.filename)
    ext, origin, mime = _require_data_file(filename)
    payload = await uploads.read_limited(file, get_settings().max_upload_mb * 1024 * 1024)
    state, repo = request.app.state, _repo(request)
    duplicate = await state.pool.fetchval(
        "SELECT title FROM datasets WHERE owner_id = $1 AND sha256 = $2 LIMIT 1",
        user.id,
        payload.sha256,
    )
    if duplicate is not None:
        raise ApiException(409, "CONFLICT", f'This file was already uploaded as "{duplicate}".')

    dataset_id = str(uuid.uuid4())
    key = original_key(user.id, dataset_id, ext)
    created = await repo.create(
        dataset_id=dataset_id,
        owner_id=user.id,
        origin=origin,
        title=uploads.title_from(filename),
        filename=filename,
        sheet="",
        s3_key_original=key,
        size_bytes=len(payload.data),
        sha256=payload.sha256,
    )
    if not created:  # concurrent duplicate upload
        raise ApiException(409, "CONFLICT", "This file was already uploaded.")
    try:
        await state.store.put(key, payload.data, mime)
        await state.task_queue.enqueue_dataset(dataset_id)
    except Exception as exc:
        logger.exception("dataset upload %s: storing or enqueueing failed", dataset_id)
        await repo.set_status(dataset_id, "FAILED", UPLOAD_FAILED)
        raise ApiException(502, "UPSTREAM_ERROR", UPLOAD_FAILED) from exc
    ds = await repo.get(dataset_id, user.id)
    if ds is None:  # deleted in between; treat as gone
        raise ApiException(404, "NOT_FOUND", "Data file not found.")
    return ok(_public(ds))


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
    await _repo(request).delete(ds.id, user.id)
    still_used = await state.pool.fetchval(
        "SELECT 1 FROM datasets WHERE s3_key_original = $1 LIMIT 1", ds.s3_key_original
    )
    keys = [ds.s3_key] if ds.s3_key else []
    if not still_used:  # other sheets of the same workbook keep the original
        keys.append(ds.s3_key_original)
    for key in keys:
        try:
            await state.store.delete(key)
        except Exception:
            logger.warning("dataset delete %s: object %s not removed", ds.id, key, exc_info=True)
    return ok({"id": ds.id, "deleted": True})
