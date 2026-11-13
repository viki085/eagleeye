"""Queue READY documents for re-chunking with the current settings (after a chunking change).

  uv run --package eagleeye-ingest-worker python -m ingest_worker.reindex --all
  uv run --package eagleeye-ingest-worker python -m ingest_worker.reindex --document <uuid>
  uv run --package eagleeye-ingest-worker python -m ingest_worker.reindex --all --dry-run

Idempotent: each document's chunks are replaced in one transaction, and documents stay READY
(searchable) throughout. The ingest worker must be running to process the queue.
"""

import argparse
import asyncio
import sys
import uuid

from eagleeye_core.config import get_settings
from eagleeye_core.queues import INGEST_QUEUE, REINDEX_TASK

from ingest_worker import repo


async def ready_documents(document: str | None) -> list[tuple[str, str, str]]:
    conn = await repo.connect(get_settings().database_url)
    try:
        if document:
            rows = await conn.fetch(
                "SELECT id, title, scope FROM documents WHERE id = $1 AND status = 'READY'",
                document,
            )
        else:
            rows = await conn.fetch(
                "SELECT id, title, scope FROM documents WHERE status = 'READY' ORDER BY created_at"
            )
        return [(str(r["id"]), r["title"], r["scope"]) for r in rows]
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true", help="every READY document")
    target.add_argument("--document", help="one document id")
    ap.add_argument("--dry-run", action="store_true", help="list, don't queue")
    args = ap.parse_args(argv)
    if args.document:
        try:
            uuid.UUID(args.document)
        except ValueError:
            print(f"not a document id: {args.document}", file=sys.stderr)
            return 2
    docs = asyncio.run(ready_documents(args.document))
    for doc_id, title, scope in docs:
        print(f"{'would queue' if args.dry_run else 'queued'}  {doc_id}  [{scope}]  {title}")
    if not args.dry_run and docs:
        from ingest_worker.celery_app import app  # import late: --dry-run needs no broker

        for doc_id, _, _ in docs:
            app.send_task(REINDEX_TASK, args=[doc_id], queue=INGEST_QUEUE)
    print(f"{len(docs)} document(s) {'found' if args.dry_run else 'queued for re-indexing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
