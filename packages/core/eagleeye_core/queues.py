"""Celery queue + task names shared by producers (api) and consumers (workers).

Producers never import worker code; they send by name.
"""

INGEST_QUEUE = "ingest"
INGEST_TASK = "ingest.ingest_document"
PROFILE_DATASET_TASK = "ingest.profile_dataset"  # same `ingest` queue
REINDEX_TASK = "ingest.reindex_document"  # same `ingest` queue; `python -m ingest_worker.reindex`

AGENT_QUEUE = "agent"
AGENT_TASK = "agent.execute_run"
