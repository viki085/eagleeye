"""Scale mode (Phase 7C): publish "answers queued plus running" to CloudWatch every 30 s.

Agent-worker autoscaling targets this divided by the number of worker tasks (C10 §2.4). Every
API task publishes the same database count, so the Average statistic stays right however many
API tasks run. Off unless QUEUE_METRIC_ENABLED is set.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

METRIC = "ActiveAnswers"
INTERVAL_S = 30


async def active_answers(pool: Any) -> int:
    return int(
        await pool.fetchval("SELECT count(*) FROM runs WHERE status IN ('QUEUED', 'RUNNING')")
    )


async def publish_once(pool: Any, cloudwatch: Any, namespace: str) -> bool:
    try:
        count = await active_answers(pool)
    except Exception:  # noqa: BLE001 - skip this datapoint rather than publish a wrong one
        logger.warning("queue metric: could not count answers", exc_info=True)
        return False
    await asyncio.to_thread(
        cloudwatch.put_metric_data,
        Namespace=namespace,
        MetricData=[{"MetricName": METRIC, "Value": float(count), "Unit": "Count"}],
    )
    return True


async def run_forever(pool: Any, cloudwatch: Any, namespace: str) -> None:
    while True:
        try:
            await publish_once(pool, cloudwatch, namespace)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("queue metric publish failed")
        await asyncio.sleep(INTERVAL_S)
