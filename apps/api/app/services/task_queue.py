"""Celery producer for every worker queue. Sends by task name; never imports worker code."""

import asyncio
from typing import Protocol

from celery import Celery
from eagleeye_core.queues import (
    AGENT_QUEUE,
    AGENT_TASK,
    INGEST_QUEUE,
    INGEST_TASK,
    PROFILE_DATASET_TASK,
)

PUBLISH_RETRY_POLICY = {"max_retries": 2, "interval_start": 0, "interval_step": 0.5}


class TaskQueue(Protocol):
    async def enqueue_ingest(self, document_id: str) -> None: ...

    async def enqueue_run(self, run_id: str) -> None: ...

    async def enqueue_dataset(self, dataset_id: str) -> None: ...


class CeleryTaskQueue:
    def __init__(self, broker_url: str) -> None:
        self._celery = Celery("eagleeye_api", broker=broker_url)
        self._celery.conf.update(task_ignore_result=True, broker_connection_retry_on_startup=True)

    async def _send(self, task: str, queue: str, arg: str) -> None:
        await asyncio.to_thread(
            self._celery.send_task,
            task,
            args=[arg],
            queue=queue,
            retry=True,
            retry_policy=PUBLISH_RETRY_POLICY,
        )

    async def enqueue_ingest(self, document_id: str) -> None:
        await self._send(INGEST_TASK, INGEST_QUEUE, document_id)

    async def enqueue_run(self, run_id: str) -> None:
        await self._send(AGENT_TASK, AGENT_QUEUE, run_id)

    async def enqueue_dataset(self, dataset_id: str) -> None:
        await self._send(PROFILE_DATASET_TASK, INGEST_QUEUE, dataset_id)
