import pytest
from gateway.src.ratelimit.limiter import InMemoryRateLimitBackend, RateLimiter


@pytest.mark.asyncio
async def test_token_bucket_initialization():
    backend = InMemoryRateLimitBackend()
    limiter = RateLimiter(backend=backend, requests_per_second=5.0, burst=10)

    res = await limiter.backend.consume(key="test:key:1", capacity=10, refill_rate=5.0, cost=1)
    assert res.allowed is True
    assert res.limit == 10
    assert res.remaining == 9  # 10 - 1
    assert res.reset_after > 0


@pytest.mark.asyncio
async def test_token_bucket_burst_exhaustion():
    backend = InMemoryRateLimitBackend()
    limiter = RateLimiter(backend=backend, requests_per_second=2.0, burst=3)

    # 3 allowed calls (burst capacity = 3)
    for i in range(3):
        res = await limiter.backend.consume(key="test:burst", capacity=3, refill_rate=2.0, cost=1)
        assert res.allowed is True
        assert res.remaining == 2 - i

    # 4th call should be rejected
    res4 = await limiter.backend.consume(key="test:burst", capacity=3, refill_rate=2.0, cost=1)
    assert res4.allowed is False
    assert res4.remaining == 0
    assert res4.retry_after > 0
    assert res4.headers["X-RateLimit-Remaining"] == "0"
    assert "Retry-After" in res4.headers


@pytest.mark.asyncio
async def test_token_bucket_refill_over_time():
    simulated_time = 1000.0

    def get_time():
        return simulated_time

    backend = InMemoryRateLimitBackend(now_func=get_time)
    limiter = RateLimiter(backend=backend, requests_per_second=2.0, burst=5)

    # Exhaust all 5 tokens
    for _ in range(5):
        res = await limiter.backend.consume(
            key="test:refill", capacity=5, refill_rate=2.0, cost=1, now=simulated_time
        )
        assert res.allowed is True

    # 6th call rejected
    res = await limiter.backend.consume(
        key="test:refill", capacity=5, refill_rate=2.0, cost=1, now=simulated_time
    )
    assert res.allowed is False

    # Advance time by 1.0 second -> 2.0 tokens refilled
    simulated_time += 1.0
    res = await limiter.backend.consume(
        key="test:refill", capacity=5, refill_rate=2.0, cost=1, now=simulated_time
    )
    assert res.allowed is True
    # 2 refilled - 1 consumed = 1 remaining
    assert res.remaining == 1

    # Consume the remaining 1
    res = await limiter.backend.consume(
        key="test:refill", capacity=5, refill_rate=2.0, cost=1, now=simulated_time
    )
    assert res.allowed is True
    assert res.remaining == 0


@pytest.mark.asyncio
async def test_token_bucket_multi_token_cost():
    backend = InMemoryRateLimitBackend()
    limiter = RateLimiter(backend=backend, requests_per_second=10.0, burst=10)

    # Consume 6 tokens at once
    res1 = await limiter.backend.consume(key="test:cost", capacity=10, refill_rate=10.0, cost=6)
    assert res1.allowed is True
    assert res1.remaining == 4

    # Try to consume 5 tokens (only 4 available) -> rejected
    res2 = await limiter.backend.consume(key="test:cost", capacity=10, refill_rate=10.0, cost=5)
    assert res2.allowed is False
    assert res2.remaining == 4  # tokens untouched when rejected
