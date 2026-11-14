import json

import asyncpg
from eagleeye_core.config import get_settings


async def create_pool() -> asyncpg.Pool:
    async def _init(conn: asyncpg.Connection) -> None:
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    return await asyncpg.create_pool(
        get_settings().database_url,
        min_size=1,
        max_size=get_settings().db_pool_max_api,
        init=_init,
    )
