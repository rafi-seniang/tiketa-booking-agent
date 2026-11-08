"""A short lock per key, held in Redis so every worker sees it. Expires on its own if a worker dies."""

import time
from typing import Protocol

from redis.asyncio import Redis


class KeyLock(Protocol):
    async def acquire(self, key: str, seconds: int) -> bool:
        """True when the caller now holds the lock, False when someone else does."""
        ...

    async def release(self, key: str) -> None: ...


class RedisKeyLock:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def acquire(self, key: str, seconds: int) -> bool:
        return bool(await self._redis.set(f"lock:{key}", "1", nx=True, ex=seconds))

    async def release(self, key: str) -> None:
        await self._redis.delete(f"lock:{key}")


class InMemoryKeyLock:
    """For tests and a single local process only: each worker would hold its own locks."""

    def __init__(self) -> None:
        self._expires_at: dict[str, float] = {}

    async def acquire(self, key: str, seconds: int) -> bool:
        now = time.monotonic()
        if self._expires_at.get(key, 0) > now:
            return False
        self._expires_at[key] = now + seconds
        return True

    async def release(self, key: str) -> None:
        self._expires_at.pop(key, None)
