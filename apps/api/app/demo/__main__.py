"""Demo account admin, run from the repo root:

uv run --package eagleeye-api python -m app.demo setup    # create / repair + seed files
uv run --package eagleeye-api python -m app.demo reset    # wipe visitor data now
"""

import asyncio
import sys

from eagleeye_core.config import get_settings
from eagleeye_core.storage import build_object_store

from app.db import create_pool
from app.demo import account
from app.services.clerk_admin import ClerkAdmin
from app.services.task_queue import CeleryTaskQueue

USAGE = "usage: python -m app.demo setup|reset"


async def main(command: str) -> int:
    settings = get_settings()
    pool = await create_pool()
    try:
        store = build_object_store()
        queue = CeleryTaskQueue(settings.redis_url)
        clerk = ClerkAdmin(settings.clerk_secret_key, settings.clerk_organization_id)
        if command == "setup":
            user_id, added = await account.setup(pool, store, queue, clerk, settings)
            print(
                f"Demo account ready ({settings.demo_username}, id {user_id}); "
                f"{added} file(s) added, spend cap ${settings.demo_usage_limit_usd:.2f}."
            )
        else:
            report = await account.reset(pool, store, queue, clerk, settings)
            print("No demo account yet: run setup first." if report is None else report)
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("setup", "reset"):
        print(USAGE)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
