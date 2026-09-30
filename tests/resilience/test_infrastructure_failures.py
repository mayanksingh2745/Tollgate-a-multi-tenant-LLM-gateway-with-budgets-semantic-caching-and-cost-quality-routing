import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from gateway.src.main import app
from gateway.src.reliability.circuit_breaker import (
    CircuitBreakerState,
    CircuitState,
)
from gateway.src.reliability.failure_classifier import FailureCategory
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_database_outage_readiness_probe_fails():
    """
    Verifies that when PostgreSQL becomes unreachable:
    1. /health/ready immediately returns HTTP 503 (signaling proxy to shed traffic).
    2. /health/live continues returning HTTP 200 (process is alive; supervisor should not kill).
    3. When PostgreSQL recovers, /health/ready returns HTTP 200.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:

        # 1. Baseline: Healthy
        with patch("gateway.src.api.health.check_db_health", AsyncMock(return_value=True)), \
             patch("gateway.src.api.health.check_redis_health", AsyncMock(return_value=True)):
            res = await client.get("/health/ready")
            assert res.status_code == 200
            assert res.json()["status"] == "ready"

        # 2. Database Outage Simulated
        with patch("gateway.src.api.health.check_db_health", AsyncMock(return_value=False)), \
             patch("gateway.src.api.health.check_redis_health", AsyncMock(return_value=True)):
            # Liveness remains alive
            live_res = await client.get("/health/live")
            assert live_res.status_code == 200
            assert live_res.json()["status"] == "alive"

            # Readiness MUST fail
            ready_res = await client.get("/health/ready")
            assert ready_res.status_code == 503
            data = ready_res.json()
            assert data["detail"]["status"] == "unhealthy"
            assert data["detail"]["database"] == "unreachable"

        # 3. Database Restoration Simulated
        with patch("gateway.src.api.health.check_db_health", AsyncMock(return_value=True)), \
             patch("gateway.src.api.health.check_redis_health", AsyncMock(return_value=True)):
            res_restored = await client.get("/health/ready")
            assert res_restored.status_code == 200
            assert res_restored.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_redis_outage_readiness_probe_fails():
    """
    Verifies that when Redis is unreachable:
    /health/ready returns HTTP 503 with redis: unreachable.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("gateway.src.api.health.check_db_health", AsyncMock(return_value=True)), \
             patch("gateway.src.api.health.check_redis_health", AsyncMock(return_value=False)):
            res = await client.get("/health/ready")
            assert res.status_code == 503
            assert res.json()["detail"]["redis"] == "unreachable"


@pytest.mark.asyncio
async def test_circuit_breaker_full_lifecycle_recovery():
    """
    Verifies circuit breaker state transitions:
    CLOSED -> (consecutive 5xx failures) -> OPEN -> (recovery timeout) -> HALF_OPEN -> (successful probe) -> CLOSED.
    """
    cb = CircuitBreakerState(
        failure_threshold=3,
        failure_window_seconds=10.0,
        open_duration_seconds=0.2,  # short timeout for testing
        half_open_max_calls=1,
    )
    provider_key = "openai:gpt-4o"

    assert cb.state == CircuitState.CLOSED
    decision = await cb.before_call(provider_key)
    assert decision.allowed is True

    # 1. Record 3 qualifying failures (5xx transient errors)
    for _ in range(3):
        await cb.record_failure(
            provider_key=provider_key,
            failure_category=FailureCategory.TRANSIENT,
        )

    # 2. Circuit must now be OPEN
    assert cb.state == CircuitState.OPEN
    decision = await cb.before_call(provider_key)
    assert decision.allowed is False
    assert decision.state == CircuitState.OPEN

    # 3. Wait for recovery timeout
    await asyncio.sleep(0.25)

    # 4. Circuit should transition to HALF_OPEN on next check
    decision_probe = await cb.before_call(provider_key)
    assert decision_probe.allowed is True
    assert decision_probe.is_probe is True
    assert cb.state == CircuitState.HALF_OPEN

    # 5. Record successful probe request
    await cb.record_success(provider_key=provider_key)

    # 6. Circuit resets to CLOSED
    assert cb.state == CircuitState.CLOSED
    decision_after = await cb.before_call(provider_key)
    assert decision_after.allowed is True
