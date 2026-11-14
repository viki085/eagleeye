"""Notebooks from notebook mode: manifest, figures and .ipynb export. Owner-only (another
user's notebook id is a 404, like every artifact)."""

import json
import re
from uuid import UUID

from eagleeye_core.envelope import ok
from eagleeye_core.storage import ObjectNotFoundError
from fastapi import APIRouter, Request, Response

from app.auth import CurrentUser
from app.errors import ApiException

router = APIRouter(prefix="/notebooks", tags=["notebooks"])

FIGURE_NAME = re.compile(r"^fig_\d{1,2}_\d{1,2}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
NOT_FOUND = "Notebook not found."


async def _owned(request: Request, notebook_id: UUID, user_id: str) -> dict:
    row = await request.app.state.pool.fetchrow(
        "SELECT id, title, s3_key, source_refs FROM artifacts "
        "WHERE id = $1 AND user_id = $2 AND type = 'notebook'",
        str(notebook_id),
        user_id,
    )
    if row is None:
        raise ApiException(404, "NOT_FOUND", NOT_FOUND)
    return dict(row)


async def _get(request: Request, key: str) -> bytes:
    try:
        return await request.app.state.artifact_store.get(key)
    except ObjectNotFoundError as exc:
        raise ApiException(404, "NOT_FOUND", "The notebook's data is no longer available.") from exc


async def _manifest(request: Request, row: dict) -> dict:
    data = json.loads((await _get(request, row["s3_key"])).decode("utf-8"))
    return data if isinstance(data, dict) else {}


def _figure_names(row: dict) -> list[str]:
    refs = row.get("source_refs") or {}
    if isinstance(refs, str):
        refs = json.loads(refs)
    return [n for n in refs.get("figures", []) if isinstance(n, str) and FIGURE_NAME.match(n)]


def _figure_key(row: dict, name: str) -> str:
    return row["s3_key"].rsplit("/", 1)[0] + f"/{name}.png"


@router.get("/{notebook_id}")
async def get_notebook(notebook_id: UUID, request: Request, user: CurrentUser) -> dict:
    row = await _owned(request, notebook_id, user.id)
    return ok(await _manifest(request, row))


@router.get("/{notebook_id}/figures/{name}")
async def get_figure(notebook_id: UUID, name: str, request: Request, user: CurrentUser) -> Response:
    row = await _owned(request, notebook_id, user.id)
    if not FIGURE_NAME.match(name) or name not in _figure_names(row):
        raise ApiException(404, "NOT_FOUND", "Figure not found.")
    png = await _get(request, _figure_key(row, name))
    if not png.startswith(PNG_SIGNATURE):
        raise ApiException(404, "NOT_FOUND", "Figure not found.")
    return Response(
        png,
        media_type="image/png",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
            "Content-Security-Policy": "default-src 'none'",
        },
    )


@router.get("/{notebook_id}/notebook.ipynb")
async def download_ipynb(notebook_id: UUID, request: Request, user: CurrentUser) -> Response:
    from app.services.notebook_export import to_ipynb

    row = await _owned(request, notebook_id, user.id)
    manifest = await _manifest(request, row)
    figures = {}
    for name in _figure_names(row):
        try:
            png = await request.app.state.artifact_store.get(_figure_key(row, name))
        except ObjectNotFoundError:
            continue
        if png.startswith(PNG_SIGNATURE):
            figures[name] = png
    filename = _UNSAFE_FILENAME.sub("_", str(row["title"]))[:60].strip("_") or "notebook"
    return Response(
        json.dumps(to_ipynb(manifest, figures), indent=1),
        media_type="application/x-ipynb+json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.ipynb"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
