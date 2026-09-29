import asyncio
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as aioredis
from gateway.src.ratelimit.limiter import (
    RateLimitBackendError,
    RedisRateLimitBackend,
)


@pytest.mark.asyncio
async def test_redis_connection_error_fail_closed():
    mock_redis = AsyncMock(spec=aioredis.Redis)
    mock_redis.eval.side_effect = aioredis.ConnectionError("Redis connection lost")

    backend = RedisRateLimitBackend(
        redis_client=mock_redis, timeout_seconds=0.1, failure_mode="closed"
    )

    with pytest.raises(RateLimitBackendError) as exc_info:
        await backend.consume(key="test:fail_closed", capacity=10, refill_rate=1.0)
    assert "Rate limiter service unavailable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_redis_connection_error_fail_open():
    mock_redis = AsyncMock(spec=aioredis.Redis)
    mock_redis.eval.side_effect = aioredis.ConnectionError("Redis connection lost")

    backend = RedisRateLimitBackend(
        redis_client=mock_redis, timeout_seconds=0.1, failure_mode="open"
    )

    # Fail-open should allow the request through
    res = await backend.consume(key="test:fail_open", capacity=10, refill_rate=1.0)
    assert res.allowed is True
    assert res.limit == 10
    assert res.remaining == 10


@pytest.mark.asyncio
async def test_redis_timeout_fail_closed():
    mock_redis = AsyncMock(spec=aioredis.Redis)

    async def slow_eval(*args, **kwargs):
        await asyncio.sleep(0.5)
        return [1, "10", "0", "0"]

    mock_redis.eval.side_effect = slow_eval

    # Timeout set to 0.05s, while eval takes 0.5s
    backend = RedisRateLimitBackend(
        redis_client=mock_redis, timeout_seconds=0.05, failure_mode="closed"
    )

    with pytest.raises(RateLimitBackendError):
        await backend.consume(key="test:timeout_closed", capacity=10, refill_rate=1.0)


@pytest.mark.asyncio
async def test_redis_timeout_fail_open():
    mock_redis = AsyncMock(spec=aioredis.Redis)

    async def slow_eval(*args, **kwargs):
        await asyncio.sleep(0.5)
        return [1, "10", "0", "0"]

    mock_redis.eval.side_effect = slow_eval

    backend = RedisRateLimitBackend(
        redis_client=mock_redis, timeout_seconds=0.05, failure_mode="open"
    )

    res = await backend.consume(key="test:timeout_open", capacity=10, refill_rate=1.0)
    assert res.allowed is True
    assert res.limit == 10
