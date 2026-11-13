import asyncio
import logging
import uuid

from eagleeye_core.queues import PROFILE_DATASET_TASK, REINDEX_TASK

from ingest_worker.celery_app import INGEST_TASK, app
from ingest_worker.errors import IngestError
from ingest_worker.pipeline import mark_failed, run_pipeline, run_reindex
from ingest_worker.tabular import mark_dataset_failed, run_dataset_pipeline

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_BACKOFF_S = 5
GENERIC_FAILURE = "Processing failed after several attempts. Try uploading again."


@app.task(name=INGEST_TASK, bind=True, max_retries=MAX_RETRIES)
def ingest_document(self, document_id: str) -> None:  # noqa: ANN001 — celery binds self
    try:
        uuid.UUID(document_id)
    except (ValueError, TypeError):
        logger.error("rejecting ingest task with invalid document id %r", document_id)
        return
    try:
        asyncio.run(run_pipeline(document_id))
    except Exception as exc:
        retries = self.request.retries
        if retries < MAX_RETRIES:
            logger.warning("ingest %s transient failure (try %d): %s", document_id, retries, exc)
            raise self.retry(exc=exc, countdown=BASE_BACKOFF_S * 2**retries) from exc
        logger.exception("ingest %s failed after %d retries", document_id, retries)
        message = exc.user_message if isinstance(exc, IngestError) else GENERIC_FAILURE
        asyncio.run(mark_failed(document_id, message))


@app.task(name=REINDEX_TASK, bind=True, max_retries=MAX_RETRIES)
def reindex_document(self, document_id: str) -> None:  # noqa: ANN001 — celery binds self
    """Re-chunk a READY document with the current settings. On final failure the document
    keeps its old chunks and stays READY (never marked FAILED by a re-index)."""
    try:
        uuid.UUID(document_id)
    except (ValueError, TypeError):
        logger.error("rejecting reindex task with invalid document id %r", document_id)
        return
    try:
        asyncio.run(run_reindex(document_id))
    except Exception as exc:
        retries = self.request.retries
        if retries < MAX_RETRIES:
            logger.warning("reindex %s transient failure (try %d): %s", document_id, retries, exc)
            raise self.retry(exc=exc, countdown=BASE_BACKOFF_S * 2**retries) from exc
        logger.exception(
            "reindex %s gave up after %d retries; old chunks kept", document_id, retries
        )


@app.task(name=PROFILE_DATASET_TASK, bind=True, max_retries=MAX_RETRIES)
def profile_dataset(self, dataset_id: str) -> None:  # noqa: ANN001 — celery binds self
    try:
        uuid.UUID(dataset_id)
    except (ValueError, TypeError):
        logger.error("rejecting dataset task with invalid id %r", dataset_id)
        return
    try:
        asyncio.run(run_dataset_pipeline(dataset_id))
    except Exception as exc:
        retries = self.request.retries
        if retries < MAX_RETRIES:
            logger.warning("dataset %s transient failure (try %d): %s", dataset_id, retries, exc)
            raise self.retry(exc=exc, countdown=BASE_BACKOFF_S * 2**retries) from exc
        logger.exception("dataset %s failed after %d retries", dataset_id, retries)
        message = exc.user_message if isinstance(exc, IngestError) else GENERIC_FAILURE
        asyncio.run(mark_dataset_failed(dataset_id, message))
