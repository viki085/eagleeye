"""Data-file pipeline: UPLOADED → PROFILING → READY | FAILED (C6 §2).

One uploaded CSV/TSV becomes one dataset. An .xlsx becomes one dataset per non-empty sheet
(≤ 5): the API's row takes the first sheet, and sibling rows are created for the rest.
"""

import json
import logging
import uuid

import asyncpg
from eagleeye_core.config import get_settings
from eagleeye_core.storage import ObjectNotFoundError, ObjectStore, build_object_store
from eagleeye_datasets.convert import convert_csv, convert_xlsx
from eagleeye_datasets.models import (
    PARQUET_MIME,
    Converted,
    Dataset,
    DatasetError,
    Limits,
    dataset_key,
)
from eagleeye_datasets.profile import profile_parquet
from eagleeye_datasets.render import profile_digest
from eagleeye_datasets.repo import DatasetRepo
from eagleeye_llm.factory import build_llm
from eagleeye_llm.gateway import ChatMessage, LLMGateway

from ingest_worker import repo
from ingest_worker.errors import PermanentIngestError, TransientIngestError

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """You describe a user's data file for an analytics assistant.
Given its profile, write TWO short sentences: what one row likely represents, and which
columns look most useful for analysis. Describe only what the names and statistics show;
never invent business rules. Plain text, no lists."""
MAX_SUMMARY_CHARS = 400


async def summarise(llm: LLMGateway | None, title: str, profile: dict) -> str:
    """Best effort: a missing summary never fails the upload."""
    if llm is None:
        return ""
    try:
        text, _ = await llm.complete(
            "fast",
            [
                ChatMessage("system", SUMMARY_PROMPT),
                ChatMessage("user", profile_digest(title, profile)),
            ],
            max_tokens=160,
        )
    except Exception:
        logger.warning("could not summarise dataset %s", title, exc_info=True)
        return ""
    return text.strip()[:MAX_SUMMARY_CHARS]


def convert(ds: Dataset, data: bytes, limits: Limits) -> list[Converted]:
    if ds.origin == "xlsx":
        return convert_xlsx(data, limits)
    return [convert_csv(data, limits)]


async def _load(store: ObjectStore, key: str) -> bytes:
    try:
        return await store.get(key)
    except ObjectNotFoundError as exc:
        raise PermanentIngestError("The uploaded file is missing from storage.") from exc
    except Exception as exc:
        raise TransientIngestError("Storage is temporarily unavailable.") from exc


async def _store_ready(
    datasets: DatasetRepo,
    store: ObjectStore,
    llm: LLMGateway | None,
    ds: Dataset,
    dataset_id: str,
    table: Converted,
) -> None:
    key = dataset_key(ds.owner_id, dataset_id)
    try:
        await store.put(key, table.parquet, PARQUET_MIME)
    except Exception as exc:
        raise TransientIngestError("Storage is temporarily unavailable.") from exc
    profile = profile_parquet(table.parquet, table.column_map)
    title = f"{ds.title} — {table.sheet}" if table.sheet else ds.title
    await datasets.mark_ready(
        dataset_id,
        title=title,
        sheet=table.sheet,
        s3_key=key,
        columns=list(table.columns),
        column_map=table.column_map,
        row_count=table.row_count,
        profile=json.loads(json.dumps(profile)),  # plain JSON types only
        summary=await summarise(llm, title, profile),
    )


async def process_dataset(
    dataset_id: str, datasets: DatasetRepo, store: ObjectStore, llm: LLMGateway | None
) -> None:
    ds = await datasets.get_for_worker(dataset_id)
    if ds is None:
        logger.info("dataset %s no longer exists; skipping", dataset_id)
        return
    s = get_settings()
    try:
        await datasets.set_status(dataset_id, "PROFILING")
        data = await _load(store, ds.s3_key_original)
        tables = convert(ds, data, Limits(s.dataset_max_rows, s.dataset_max_columns))
        await _store_ready(datasets, store, llm, ds, dataset_id, tables[0])
        for table in tables[1:]:
            sibling = str(uuid.uuid4())
            created = await datasets.create(
                dataset_id=sibling,
                owner_id=ds.owner_id,
                origin=ds.origin,
                title=ds.title,
                filename=ds.filename,
                sheet=table.sheet,
                s3_key_original=ds.s3_key_original,
                size_bytes=ds.size_bytes,
                sha256=ds.sha256,
            )
            if created:
                await _store_ready(datasets, store, llm, ds, sibling, table)
        logger.info("dataset %s READY (%d table(s))", dataset_id, len(tables))
    except DatasetError as exc:
        logger.warning("dataset %s rejected: %s", dataset_id, exc.user_message)
        await datasets.set_status(dataset_id, "FAILED", exc.user_message)


async def run_dataset_pipeline(dataset_id: str) -> None:
    s = get_settings()
    conn: asyncpg.Connection = await repo.connect(s.database_url)
    try:
        llm = build_llm(s, fallbacks=False)
        await process_dataset(dataset_id, DatasetRepo(conn), build_object_store(), llm)
    finally:
        await conn.close()


async def mark_dataset_failed(dataset_id: str, message: str) -> None:
    conn = await repo.connect(get_settings().database_url)
    try:
        await DatasetRepo(conn).set_status(dataset_id, "FAILED", message)
    finally:
        await conn.close()
