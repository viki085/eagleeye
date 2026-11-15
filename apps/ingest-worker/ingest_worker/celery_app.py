"""Celery app for the `ingest` queue (Redis broker, no result backend).

Run (Windows needs the solo pool), from the repo root:
  uv run --package eagleeye-ingest-worker celery -A ingest_worker.celery_app worker \
      --pool=solo -Q ingest -l info
"""

from celery import Celery, signals
from eagleeye_core.config import get_settings
from eagleeye_core.logs import configure_logging
from eagleeye_core.queues import INGEST_QUEUE, INGEST_TASK
from eagleeye_llm.env import export_provider_keys

__all__ = ["INGEST_QUEUE", "INGEST_TASK", "app"]

_settings = get_settings()


@signals.setup_logging.connect
def _logging(**_: object) -> None:
    """Our format (JSON in the cloud) instead of Celery's own logging setup."""
    configure_logging(_settings, "ingest-worker")


export_provider_keys(_settings.openai_api_key, _settings.anthropic_api_key)

app = Celery("eagleeye_ingest", broker=_settings.redis_url, include=["ingest_worker.tasks"])
app.conf.update(
    task_default_queue=INGEST_QUEUE,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
)
