"""Model tokens per caller per day, counted in Redis so every worker and replica shares one count.

The rate limit counts requests. This counts what they cost: one chat turn can be a few hundred tokens or thirty
thousand. A day is a UTC day, so the budget resets at 07:00 in Jakarta.
"""

import time
from typing import Protocol

from redis.asyncio import Redis

DAY_SECONDS = 86_400


class TokenBudget(Protocol):
    async def used(self, caller: str) -> int:
        """Tokens the caller has used today."""
        ...

    async def add(self, caller: str, tokens: int) -> None: ...


def day_key(caller: str, now: float) -> str:
    return f"tokens:{caller}:{int(now // DAY_SECONDS)}"


def seconds_to_reset(now: float) -> int:
    return DAY_SECONDS - int(now % DAY_SECONDS)


class RedisTokenBudget:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def used(self, caller: str) -> int:
        return int(await self._redis.get(day_key(caller, time.time())) or 0)

    async def add(self, caller: str, tokens: int) -> None:
        if tokens <= 0:
            return
        key = day_key(caller, time.time())
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incrby(key, tokens)
            pipe.expire(key, 2 * DAY_SECONDS)
            await pipe.execute()


class InMemoryTokenBudget:
    """For tests and a single local process only: each worker would count on its own."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    async def used(self, caller: str) -> int:
        return self._counts.get(day_key(caller, time.time()), 0)

    async def add(self, caller: str, tokens: int) -> None:
        key = day_key(caller, time.time())
        self._counts[key] = self._counts.get(key, 0) + max(tokens, 0)
