"""Result tables from SQL runs: paged JSON view + CSV export. Owner-only."""

import json
import logging
import re
from uuid import UUID

from eagleeye_core.envelope import ok
from eagleeye_core.storage import ObjectNotFoundError
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.auth import CurrentUser
from app.errors import ApiException
from app.services import artifact_reader

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/artifacts", tags=["artifacts"])

MAX_PAGE = 200
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _as_dict(raw: object) -> dict:
    """Tolerates rows written double-encoded (a JSON string inside jsonb) before the fix."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


async def _owned(request: Request, artifact_id: UUID, user_id: str) -> dict:
    row = await request.app.state.pool.fetchrow(
        "SELECT id, title, s3_key, columns, row_count, truncated, source_refs, created_at "
        "FROM artifacts WHERE id = $1 AND user_id = $2",
        str(artifact_id),
        user_id,
    )
    if row is None:
        raise ApiException(404, "NOT_FOUND", "Result not found.")
    return dict(row)


async def _load(request: Request, row: dict):  # noqa: ANN202
    try:
        data = await request.app.state.artifact_store.get(row["s3_key"])
    except ObjectNotFoundError as exc:
        raise ApiException(404, "NOT_FOUND", "Result data is no longer available.") from exc
    return artifact_reader.read_table(data)


@router.get("/{artifact_id}")
async def get_artifact(
    artifact_id: UUID,
    request: Request,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=MAX_PAGE),
) -> dict:
    row = await _owned(request, artifact_id, user.id)
    page = artifact_reader.page(await _load(request, row), offset, limit)
    refs = _as_dict(row["source_refs"])
    return ok(
        {
            "id": str(row["id"]),
            "title": row["title"],
            "sql": refs.get("sql", ""),
            "columns": page.columns,
            "rows": page.rows,
            "offset": offset,
            "total": page.total,
            "truncated": row["truncated"],
        }
    )


@router.get("/{artifact_id}/csv")
async def download_csv(artifact_id: UUID, request: Request, user: CurrentUser) -> StreamingResponse:
    row = await _owned(request, artifact_id, user.id)
    table = await _load(request, row)
    name = _UNSAFE_FILENAME.sub("_", row["title"]).strip("_")[:60] or "result"
    return StreamingResponse(
        artifact_reader.csv_lines(table),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )
