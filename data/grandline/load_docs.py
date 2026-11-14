"""Load the Grand Line document library into an EagleEye environment as enterprise documents.

  uv run --package eagleeye-api python data/grandline/load_docs.py [--limit N]

Uses the same path as an upload: the file goes to the object store under a server-made key,
a documents row is created (scope 'enterprise', uploaded by the first admin), and the ingest
worker is queued to parse, chunk and embed it. Documents already loaded (same SHA-256) are
skipped, so the script can be re-run safely. Needs the API's settings (.env) and the ingest
worker running.
"""

import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from pathlib import Path

import asyncpg
from app.repos.documents import insert_document
from app.services.task_queue import CeleryTaskQueue
from app.services.uploads import ALLOWED_EXTENSIONS, extension_of, object_key
from eagleeye_core.config import get_settings
from eagleeye_core.storage import build_object_store

OUT = Path(__file__).resolve().parent / "out"


async def main(limit: int | None) -> int:
    s = get_settings()
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))[:limit]
    pool = await asyncpg.create_pool(s.database_url, min_size=1, max_size=4)
    store = build_object_store()
    await store.ensure_bucket()
    queue = CeleryTaskQueue(s.redis_url)
    try:
        admin = await pool.fetchval(
            "SELECT id FROM users WHERE role = 'admin' AND status = 'active' "
            "ORDER BY created_at LIMIT 1")
        if admin is None:
            print("No active admin user; create one in the admin console first.")
            return 1
        known = {r["sha256"] for r in await pool.fetch(
            "SELECT sha256 FROM documents WHERE scope = 'enterprise'")}
        loaded = skipped = 0
        for d in manifest:
            path = OUT / d["path"]
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest in known:
                skipped += 1
                continue
            ext = extension_of(path.name)
            doc_id = str(uuid.uuid4())
            key = object_key("enterprise", doc_id, ext)
            await store.put(key, data, ALLOWED_EXTENSIONS[ext])
            await insert_document(pool, doc_id=doc_id, scope="enterprise", user_id=str(admin),
                                  title=d["title"][:120], filename=path.name,
                                  mime=ALLOWED_EXTENSIONS[ext], size_bytes=len(data),
                                  sha256=digest, s3_key=key)
            await queue.enqueue_ingest(doc_id)
            known.add(digest)
            loaded += 1
        print(f"Queued {loaded} documents for ingestion; {skipped} were already loaded.")
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    sys.exit(asyncio.run(main(ap.parse_args().limit)))
