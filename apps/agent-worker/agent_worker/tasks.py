import logging
import uuid

from agent_worker.celery_app import AGENT_TASK, app
from agent_worker.runtime import run_agent

logger = logging.getLogger(__name__)


@app.task(name=AGENT_TASK)
def execute_run(run_id: str) -> None:
    """No Celery retries: a run streams to a user live, so a crash fails the run
    (the runner emits run.error) rather than silently replaying it."""
    try:
        uuid.UUID(run_id)
    except (ValueError, TypeError):
        logger.error("rejecting agent task with invalid run id %r", run_id)
        return
    run_agent(run_id)
