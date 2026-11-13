"""Kill switches (C8 §6): Redis flags an admin flips from the console to turn a capability off.

Set → the capability is OFF. Reads fail open (a Redis error leaves the capability on), so a
Redis outage never takes the whole app down on its own.
"""

import logging
from typing import Literal, Protocol

logger = logging.getLogger(__name__)

Switch = Literal["chat", "sql", "analysis", "uploads"]
SWITCHES: tuple[Switch, ...] = ("chat", "sql", "analysis", "uploads")
DESCRIPTIONS: dict[Switch, str] = {
    "chat": "New questions are refused (answers already running finish).",
    "sql": "Database querying is turned off for new answers.",
    "analysis": "Data-file analysis (sandbox) is turned off for new answers.",
    "uploads": "Document and data-file uploads are refused.",
}


class RedisLike(Protocol):
    async def exists(self, *names: str) -> int: ...

    async def mget(self, keys: list[str]) -> list[bytes | str | None]: ...


def switch_key(name: Switch) -> str:
    return f"kill:{name}"


async def is_killed(redis: RedisLike, name: Switch) -> bool:
    try:
        return bool(await redis.exists(switch_key(name)))
    except Exception:
        logger.warning("could not read kill switch %s; treating it as off", name, exc_info=True)
        return False


async def killed_switches(redis: RedisLike) -> dict[Switch, bool]:
    try:
        values = await redis.mget([switch_key(s) for s in SWITCHES])
    except Exception:
        logger.warning("could not read kill switches; treating them as off", exc_info=True)
        return dict.fromkeys(SWITCHES, False)
    return {s: v is not None for s, v in zip(SWITCHES, values, strict=True)}
