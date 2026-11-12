"""Celery queue + task names shared by producers (api) and consumers (workers).

Producers never import worker code; they send by name.
"""

INGEST_QUEUE = "ingest"
INGEST_TASK = "ingest.ingest_document"

AGENT_QUEUE = "agent"
AGENT_TASK = "agent.execute_run"
