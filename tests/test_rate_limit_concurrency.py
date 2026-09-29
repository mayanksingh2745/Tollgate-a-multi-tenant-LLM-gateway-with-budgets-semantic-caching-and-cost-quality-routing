import asyncio

import pytest
from gateway.src.ratelimit.limiter import InMemoryRateLimitBackend, RateLimiter


@pytest.mark.asyncio
async def test_concurrent_rate_limiting_atomic_drain():
    backend = InMemoryRateLimitBackend()
    limiter = RateLimiter(backend=backend, requests_per_second=1.0, burst=15)
    key = "test:concurrency:atomic"

    # Launch 50 concurrent requests simultaneously
    async def make_request():
        return await limiter.backend.consume(
            key=key,
            capacity=15,
            refill_rate=1.0,
            cost=1,
            now=1000.0,  # Fixed time so no refill occurs during execution
        )

    tasks = [make_request() for _ in range(50)]
    results = await asyncio.gather(*tasks)

    allowed_count = sum(1 for r in results if r.allowed)
    rejected_count = sum(1 for r in results if not r.allowed)

    assert allowed_count == 15, f"Expected exactly 15 allowed requests, got {allowed_count}"
    assert rejected_count == 35, f"Expected exactly 35 rejected requests, got {rejected_count}"

    # Verify final bucket status
    final_res = await limiter.backend.consume(
        key=key,
        capacity=15,
        refill_rate=1.0,
        cost=1,
        now=1000.0,
    )
    assert final_res.allowed is False
    assert final_res.remaining == 0
