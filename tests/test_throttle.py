import pytest
from redis.asyncio import Redis

from tutor_bot.services.throttle import BusyError, RateLimitedError, Throttle


async def test_second_concurrent_request_is_busy(redis: Redis) -> None:
    throttle = Throttle(redis, per_minute=10)

    async with throttle.slot(1):
        with pytest.raises(BusyError):
            async with throttle.slot(1):
                pass
        # другой пользователь не ждёт
        async with throttle.slot(2):
            pass


async def test_lock_released_after_request_and_after_error(redis: Redis) -> None:
    throttle = Throttle(redis, per_minute=10)

    async with throttle.slot(1):
        pass
    with pytest.raises(ValueError):
        async with throttle.slot(1):
            raise ValueError
    async with throttle.slot(1):
        pass


async def test_rate_limit(redis: Redis) -> None:
    throttle = Throttle(redis, per_minute=3)
    for _ in range(3):
        async with throttle.slot(1):
            pass

    with pytest.raises(RateLimitedError):
        async with throttle.slot(1):
            pass
    # отказ по частоте не оставляет блокировку
    with pytest.raises(RateLimitedError):
        async with throttle.slot(1):
            pass
