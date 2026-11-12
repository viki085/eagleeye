import asyncio
from typing import Protocol

from celery import Celery
from eagleeye_core.queues import INGEST_QUEUE, INGEST_TASK

PUBLISH_RETRY_POLICY = {"max_retries": 2, "interval_start": 0, "interval_step": 0.5}


class IngestQueue(Protocol):
    async def enqueue(self, document_id: str) -> None: ...


class CeleryIngestQueue:
    """Producer only: sends by task name, never imports worker code."""

    def __init__(self, broker_url: str) -> None:
        self._celery = Celery("eagleeye_api", broker=broker_url)
        self._celery.conf.update(task_ignore_result=True, broker_connection_retry_on_startup=True)

    async def enqueue(self, document_id: str) -> None:
        await asyncio.to_thread(
            self._celery.send_task,
            INGEST_TASK,
            args=[document_id],
            queue=INGEST_QUEUE,
            retry=True,
            retry_policy=PUBLISH_RETRY_POLICY,
        )
