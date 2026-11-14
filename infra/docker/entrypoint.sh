#!/bin/sh
# Starts the service named by $SERVICE. `exec` makes it PID 1, so `docker stop` (SIGTERM) gives
# uvicorn a graceful shutdown and Celery a warm shutdown (running tasks finish; compose allows
# 120 s via stop_grace_period).
set -eu

case "$SERVICE" in
  api)
    # proxy headers: only the configured proxy (e.g. CloudFront/the load balancer) may set the
    # client address; the default trusts nobody but localhost
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
      --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
      --timeout-graceful-shutdown 30
    ;;
  gateway)
    exec uvicorn gateway.main:app --host 0.0.0.0 --port 8100 --timeout-graceful-shutdown 30
    ;;
  agent-worker)
    exec celery -A agent_worker.celery_app worker --pool=threads \
      --concurrency "${AGENT_CONCURRENCY:-8}" -Q agent -l info -n "agent@%h"
    ;;
  ingest-worker)
    exec celery -A ingest_worker.celery_app worker --pool=solo -Q ingest -l info -n "ingest@%h"
    ;;
  *)
    echo "Unknown SERVICE '$SERVICE' (expected api, gateway, agent-worker or ingest-worker)" >&2
    exit 64
    ;;
esac
