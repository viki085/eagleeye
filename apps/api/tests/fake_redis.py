"""In-memory stand-in for the few Redis commands the API uses (limits, switches, streams)."""


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.data: dict[str, int | str] = {}
        self.fail = fail

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("redis down")

    async def incr(self, key: str) -> int:
        self._check()
        self.data[key] = int(self.data.get(key, 0)) + 1
        return int(self.data[key])

    async def decr(self, key: str) -> int:
        self._check()
        self.data[key] = int(self.data.get(key, 0)) - 1
        return int(self.data[key])

    async def expire(self, key: str, seconds: int) -> None:
        self._check()

    async def delete(self, *keys: str) -> None:
        self._check()
        for key in keys:
            self.data.pop(key, None)

    def pipeline(self) -> "FakePipeline":
        return FakePipeline(self)

    async def hgetall(self, key: str) -> dict:
        self._check()
        value = self.data.get(key)
        return value if isinstance(value, dict) else {}

    async def exists(self, *keys: str) -> int:
        self._check()
        return sum(1 for k in keys if k in self.data)

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        self._check()
        if nx and key in self.data:
            return None  # like Redis: SET NX on an existing key does nothing
        self.data[key] = value
        return True

    async def get(self, key: str) -> str | None:
        self._check()
        value = self.data.get(key)
        return None if value is None else str(value)

    async def mget(self, keys: list[str]) -> list:
        self._check()
        return [self.data.get(k) for k in keys]

    async def llen(self, key: str) -> int:
        self._check()
        return 0


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis, self.ops = redis, []

    def hgetall(self, key: str) -> "FakePipeline":
        self.ops.append(key)
        return self

    async def execute(self) -> list:
        return [await self.redis.hgetall(k) for k in self.ops]
