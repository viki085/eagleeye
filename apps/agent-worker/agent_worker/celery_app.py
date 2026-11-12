"""Celery app for the `agent` queue (Redis broker, no result backend).

Run from the repo root (thread pool works on Windows and serves chats concurrently):
  uv run --package eagleeye-agent-worker celery -A agent_worker.celery_app worker \
      --pool=threads --concurrency=8 -Q agent -l info
"""

import logging

from celery import Celery
from eagleeye_core.config import get_settings
from eagleeye_core.queues import AGENT_QUEUE, AGENT_TASK
from eagleeye_llm.env import export_provider_keys

__all__ = ["AGENT_QUEUE", "AGENT_TASK", "app"]

logging.getLogger("httpx").setLevel(logging.WARNING)

_settings = get_settings()
export_provider_keys(_settings.openai_api_key, _settings.anthropic_api_key)

app = Celery("eagleeye_agent", broker=_settings.redis_url, include=["agent_worker.tasks"])
app.conf.update(
    task_default_queue=AGENT_QUEUE,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
)
