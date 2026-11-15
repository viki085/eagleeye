"""Is EagleEye idle? For the demo machine's stop timer (Phase 7 wake/sleep).

Exit code 0 = idle for at least --minutes (or never used since the machine started and it
has been up that long), 1 = in use, 2 = can't tell (Redis unreachable: never stop then).

  uv run --package eagleeye-api python scripts/idle_check.py --minutes 30
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

import redis.asyncio as aioredis
from eagleeye_core.config import get_settings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.activity import idle_seconds  # noqa: E402


def _uptime_s() -> float:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except OSError:
        return 0.0


async def main(minutes: float) -> int:
    client = aioredis.from_url(get_settings().redis_url, socket_connect_timeout=5)
    try:
        idle = await idle_seconds(client, time.time())
    except Exception as exc:  # noqa: BLE001
        print(f"cannot tell: {exc}")
        return 2
    finally:
        await client.aclose()
    if idle is None:  # nobody used it since it started: idle once it has been up long enough
        idle = _uptime_s()
    print(f"idle for {idle / 60:.1f} min")
    return 0 if idle >= minutes * 60 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--minutes", type=float, default=30.0)
    sys.exit(asyncio.run(main(parser.parse_args().minutes)))
