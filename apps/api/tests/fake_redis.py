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

    async def delete(self, key: str) -> None:
        self._check()
        self.data.pop(key, None)

    async def exists(self, *keys: str) -> int:
        self._check()
        return sum(1 for k in keys if k in self.data)

    async def set(self, key: str, value: str) -> None:
        self._check()
        self.data[key] = value

    async def mget(self, keys: list[str]) -> list:
        self._check()
        return [self.data.get(k) for k in keys]

    async def llen(self, key: str) -> int:
        self._check()
        return 0
