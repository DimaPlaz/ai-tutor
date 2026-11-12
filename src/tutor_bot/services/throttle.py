"""Антиспам: один запрос к LLM одновременно на пользователя и ограничение частоты."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from redis.asyncio import Redis
from redis.exceptions import LockError


class BusyError(Exception):
    """У пользователя уже идёт запрос к LLM."""


class RateLimitedError(Exception):
    """Слишком много запросов за последнюю минуту."""


class Throttle:
    def __init__(self, redis: Redis, per_minute: int, lock_ttl_seconds: int = 180) -> None:
        self._redis = redis
        self._per_minute = per_minute
        # Страховка: если процесс упадёт посреди запроса, блокировка снимется сама
        self._lock_ttl = lock_ttl_seconds

    @asynccontextmanager
    async def slot(self, user_id: int) -> AsyncIterator[None]:
        lock = self._redis.lock(f"throttle:busy:{user_id}", timeout=self._lock_ttl)
        if not await lock.acquire(blocking=False):
            raise BusyError
        try:
            await self._count_request(user_id)
            yield
        finally:
            # Если блокировка истекла по таймауту, она уже не наша — снимать нечего
            with suppress(LockError):
                await lock.release()

    async def _count_request(self, user_id: int) -> None:
        window = int(time.time() // 60)
        key = f"throttle:rate:{user_id}:{window}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, 60)
        if count > self._per_minute:
            raise RateLimitedError
