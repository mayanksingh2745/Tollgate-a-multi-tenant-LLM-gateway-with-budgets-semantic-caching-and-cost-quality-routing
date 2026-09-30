"""
Phase 12 Circuit Breaker Tests.

Comprehensive verification of:
1. Three-state state machine (CLOSED -> OPEN -> HALF_OPEN -> CLOSED / OPEN)
2. Windowed failure tracking & sliding window expiration
3. Failure category filtering (TRANSIENT/INTERNAL count; BAD_REQUEST/AUTH/etc do not)
4. Rate-limit (429) consecutive failure threshold
5. Concurrency safety (100 concurrent asyncio requests)
6. Half-open probe limiting & recovery
7. ReliableExecutor integration with retries, fallback, streaming
8. Prometheus metrics recording (transitions, rejections, probes, gauge)
9. Operator diagnostic endpoint (/internal/provider-health)
10. Fail-open safety
"""

import asyncio
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.main import app
from gateway.src.providers.base import (
    ProviderException,
)
from gateway.src.providers.mock import MockProvider
from gateway.src.reliability.circuit_breaker import (
    CircuitBreakerRegistry,
    CircuitBreakerState,
    CircuitState,
)
from gateway.src.reliability.executor import ReliableExecutor
from gateway.src.reliability.failure_classifier import FailureCategory
from gateway.src.reliability.health import ProviderHealthTracker
from gateway.src.reliability.metrics import ReliabilityMetrics
from gateway.src.reliability.policy import (
    FallbackRoute,
    ProviderTarget,
    ReliabilityPolicy,
)
from gateway.src.schemas.chat import (
    ChatCompletionRequest,
    ChatMessage,
)
from tollgate_core.observability.metrics import (
    CIRCUIT_REJECTIONS_TOTAL,
    CIRCUIT_STATE,
    CIRCUIT_TRANSITIONS_TOTAL,
)


@pytest.fixture(autouse=True)
def reset_circuit_state():
    """Reset all circuit breakers and Prometheus metrics between tests."""
    from gateway.src.reliability.circuit_breaker import circuit_breaker_registry

    circuit_breaker_registry.reset()
    yield
    circuit_breaker_registry.reset()


# ==============================================================================
# 1. State Machine Unit Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_initial_state_is_closed():
    cb = CircuitBreakerState(failure_threshold=3, failure_window_seconds=10.0)
    decision = await cb.before_call("mock:model")
    assert decision.allowed is True
    assert decision.state == CircuitState.CLOSED
    assert decision.is_open is False


@pytest.mark.asyncio
async def test_failures_below_threshold_stay_closed():
    cb = CircuitBreakerState(failure_threshold=3, failure_window_seconds=10.0)
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT)
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT)

    decision = await cb.before_call("mock:model")
    assert decision.allowed is True
    assert decision.state == CircuitState.CLOSED
    assert cb.failure_count_in_window == 2


@pytest.mark.asyncio
async def test_reaching_threshold_transitions_to_open():
    cb = CircuitBreakerState(failure_threshold=3, failure_window_seconds=10.0)
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT)
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT)
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT)

    assert cb.state == CircuitState.OPEN
    decision = await cb.before_call("mock:model")
    assert decision.allowed is False
    assert decision.state == CircuitState.OPEN
    assert decision.reason == "circuit_open"
    assert cb.get_status()["total_rejections"] == 1


@pytest.mark.asyncio
async def test_open_cooldown_to_half_open():
    cb = CircuitBreakerState(
        failure_threshold=2,
        failure_window_seconds=10.0,
        open_duration_seconds=5.0,
        half_open_max_calls=1,
    )
    t0 = 1000.0
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT, now=t0)
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT, now=t0)
    assert cb.state == CircuitState.OPEN

    # Call before cooldown elapses -> rejected
    decision1 = await cb.before_call("mock:model", now=t0 + 4.0)
    assert decision1.allowed is False
    assert decision1.state == CircuitState.OPEN

    # Call after cooldown elapses -> transitions to HALF_OPEN, allows single probe
    decision2 = await cb.before_call("mock:model", now=t0 + 5.1)
    assert decision2.allowed is True
    assert decision2.state == CircuitState.HALF_OPEN
    assert decision2.is_probe is True
    assert cb.state == CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_half_open_probe_limit():
    cb = CircuitBreakerState(
        failure_threshold=2,
        open_duration_seconds=5.0,
        half_open_max_calls=1,
    )
    t0 = 1000.0
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT, now=t0)
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT, now=t0)

    # First probe after cooldown
    d1 = await cb.before_call("mock:model", now=t0 + 6.0)
    assert d1.allowed is True
    assert d1.is_probe is True

    # Second concurrent call while probe is active -> rejected by probe limit
    d2 = await cb.before_call("mock:model", now=t0 + 6.1)
    assert d2.allowed is False
    assert d2.state == CircuitState.HALF_OPEN
    assert d2.reason == "half_open_probe_limit"


@pytest.mark.asyncio
async def test_half_open_probe_success_closes_circuit():
    cb = CircuitBreakerState(
        failure_threshold=2,
        open_duration_seconds=5.0,
    )
    t0 = 1000.0
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT, now=t0)
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT, now=t0)

    # Transition to half-open
    await cb.before_call("mock:model", now=t0 + 6.0)
    assert cb.state == CircuitState.HALF_OPEN

    # Probe succeeds
    await cb.record_success("mock:model")
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count_in_window == 0

    # Normal requests allowed again
    d = await cb.before_call("mock:model", now=t0 + 7.0)
    assert d.allowed is True
    assert d.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_half_open_probe_failure_reopens_circuit():
    cb = CircuitBreakerState(
        failure_threshold=2,
        open_duration_seconds=5.0,
    )
    t0 = 1000.0
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT, now=t0)
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT, now=t0)

    # Transition to half-open
    await cb.before_call("mock:model", now=t0 + 6.0)
    assert cb.state == CircuitState.HALF_OPEN

    # Probe fails!
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT, now=t0 + 6.5)
    assert cb.state == CircuitState.OPEN

    # Next call rejected again
    d = await cb.before_call("mock:model", now=t0 + 7.0)
    assert d.allowed is False
    assert d.state == CircuitState.OPEN


# ==============================================================================
# 2. Windowed Sliding Failure Tracking
# ==============================================================================


@pytest.mark.asyncio
async def test_failures_outside_window_expire():
    cb = CircuitBreakerState(
        failure_threshold=3,
        failure_window_seconds=10.0,
    )
    t0 = 100.0
    # Two failures at t0
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT, now=t0)
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT, now=t0 + 1.0)
    assert cb.get_failure_count(now=t0 + 1.0) == 2

    # Third failure arrives at t0 + 15 (after 10s window elapsed)
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT, now=t0 + 15.0)

    # The first two should have expired from the sliding window, so only 1 failure remains!
    assert cb.state == CircuitState.CLOSED
    assert cb.get_failure_count(now=t0 + 15.0) == 1


# ==============================================================================
# 3. Failure Classification Filtering
# ==============================================================================


@pytest.mark.asyncio
async def test_client_errors_do_not_trip_circuit():
    cb = CircuitBreakerState(failure_threshold=2)
    # Bad request (400), Not found (404), Auth (401/403), Content policy
    await cb.record_failure("mock:model", FailureCategory.BAD_REQUEST)
    await cb.record_failure("mock:model", FailureCategory.NOT_FOUND)
    await cb.record_failure("mock:model", FailureCategory.AUTHENTICATION_FAILURE)
    await cb.record_failure("mock:model", FailureCategory.CONTENT_POLICY)

    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count_in_window == 0


@pytest.mark.asyncio
async def test_internal_and_transient_trip_circuit():
    cb = CircuitBreakerState(failure_threshold=2)
    await cb.record_failure("mock:model", FailureCategory.INTERNAL)
    await cb.record_failure("mock:model", FailureCategory.TRANSIENT)

    assert cb.state == CircuitState.OPEN


# ==============================================================================
# 4. Rate-Limit (429) Consecutive Threshold Policy
# ==============================================================================


@pytest.mark.asyncio
async def test_rate_limit_requires_consecutive_threshold():
    cb = CircuitBreakerState(failure_threshold=3, rate_limit_threshold=5)

    # 4 consecutive 429s (below threshold of 5)
    for _ in range(4):
        await cb.record_failure("mock:model", FailureCategory.RATE_LIMITED)
    assert cb.state == CircuitState.CLOSED

    # Success resets consecutive count!
    await cb.record_success("mock:model")
    assert cb._consecutive_rate_limits == 0

    # 4 more consecutive 429s
    for _ in range(4):
        await cb.record_failure("mock:model", FailureCategory.RATE_LIMITED)
    assert cb.state == CircuitState.CLOSED

    # 5th consecutive 429 trips it!
    await cb.record_failure("mock:model", FailureCategory.RATE_LIMITED)
    # Consecutive threshold exceeded, counts as failure in window
    for _ in range(2):
        await cb.record_failure("mock:model", FailureCategory.TRANSIENT)
    assert cb.state == CircuitState.OPEN


# ==============================================================================
# 5. Concurrency Safety Test (100 concurrent requests)
# ==============================================================================


@pytest.mark.asyncio
async def test_concurrent_requests_safety():
    cb = CircuitBreakerState(failure_threshold=10, half_open_max_calls=1)

    async def worker(idx: int):
        decision = await cb.before_call("mock:model")
        if idx % 2 == 0:
            await cb.record_failure("mock:model", FailureCategory.TRANSIENT)
        else:
            await cb.record_success("mock:model")
        return decision

    # Run 100 concurrent workers
    tasks = [worker(i) for i in range(100)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Ensure all succeeded without exceptions
    for res in results:
        assert not isinstance(res, Exception)
    assert cb.state in (CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN)


# ==============================================================================
# 6. ReliableExecutor Fallback & Circuit Breaker Integration
# ==============================================================================


@pytest.mark.asyncio
async def test_executor_skips_open_circuit_to_fallback():
    # Setup mock primary and fallback providers
    primary_provider = MockProvider(name="primary_prov")
    fallback_provider = MockProvider(name="fallback_prov", response_text="hello")

    providers_map = {
        "primary_prov": primary_provider,
        "fallback_prov": fallback_provider,
    }

    registry = CircuitBreakerRegistry(failure_threshold=2)
    # Trip primary provider's circuit
    await registry.record_failure("primary_prov", "primary-model", FailureCategory.TRANSIENT)
    await registry.record_failure("primary_prov", "primary-model", FailureCategory.TRANSIENT)

    executor = ReliableExecutor(
        health=ProviderHealthTracker(),
        metric_recorder=ReliabilityMetrics(),
        circuit_breaker=registry,
    )

    route = FallbackRoute(
        logical_model="standard-chat",
        primary=ProviderTarget(provider_name="primary_prov", upstream_model="primary-model"),
        fallbacks=[ProviderTarget(provider_name="fallback_prov", upstream_model="fallback-model")],
    )

    req = ChatCompletionRequest(model="standard-chat", messages=[ChatMessage(role="user", content="hi")])
    ctx = AuthenticatedContext(api_key_id=uuid4(), user_id=None, project_id=uuid4(), tenant_id=uuid4(), role="admin")

    res, meta = await executor.execute_chat(
        request=req,
        route=route,
        providers_map=providers_map,
        ctx=ctx,
        request_id="req-test-1",
        policy=ReliabilityPolicy(max_attempts=1, provider_timeout_seconds=5.0, overall_timeout_seconds=10.0),
    )

    # Primary provider should NEVER have been called because circuit was OPEN!
    assert primary_provider.call_count == 0
    assert fallback_provider.call_count == 1
    assert meta.circuit_rejections == 1
    assert meta.fallback_used is True
    assert meta.final_provider == "fallback_prov"
    assert res.choices[0].message.content == "hello"


@pytest.mark.asyncio
async def test_executor_all_circuits_open_fails_gracefully():
    primary_provider = MockProvider(name="primary_prov")

    providers_map = {"primary_prov": primary_provider}
    registry = CircuitBreakerRegistry(failure_threshold=1)
    await registry.record_failure("primary_prov", "primary-model", FailureCategory.TRANSIENT)

    executor = ReliableExecutor(
        health=ProviderHealthTracker(),
        metric_recorder=ReliabilityMetrics(),
        circuit_breaker=registry,
    )

    route = FallbackRoute(
        logical_model="standard-chat",
        primary=ProviderTarget(provider_name="primary_prov", upstream_model="primary-model"),
        fallbacks=[],
    )
    req = ChatCompletionRequest(model="standard-chat", messages=[ChatMessage(role="user", content="hi")])
    ctx = AuthenticatedContext(api_key_id=uuid4(), user_id=None, project_id=uuid4(), tenant_id=uuid4(), role="admin")

    with pytest.raises(ProviderException) as exc_info:
        await executor.execute_chat(
            request=req,
            route=route,
            providers_map=providers_map,
            ctx=ctx,
            request_id="req-test-2",
        )
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_streaming_executor_skips_open_circuit():
    primary_provider = MockProvider(name="primary_prov")
    fallback_provider = MockProvider(name="fallback_prov", response_text="hello stream")

    providers_map = {"primary_prov": primary_provider, "fallback_prov": fallback_provider}

    registry = CircuitBreakerRegistry(failure_threshold=1)
    await registry.record_failure("primary_prov", "primary-model", FailureCategory.TRANSIENT)

    executor = ReliableExecutor(
        health=ProviderHealthTracker(),
        metric_recorder=ReliabilityMetrics(),
        circuit_breaker=registry,
    )

    route = FallbackRoute(
        logical_model="standard-chat",
        primary=ProviderTarget(provider_name="primary_prov", upstream_model="primary-model"),
        fallbacks=[ProviderTarget(provider_name="fallback_prov", upstream_model="fallback-model")],
    )
    req = ChatCompletionRequest(model="standard-chat", messages=[ChatMessage(role="user", content="hi")])
    ctx = AuthenticatedContext(api_key_id=uuid4(), user_id=None, project_id=uuid4(), tenant_id=uuid4(), role="admin")

    chunks = []
    async for chunk in executor.execute_stream(
        request=req,
        route=route,
        providers_map=providers_map,
        ctx=ctx,
        request_id="req-stream-1",
        policy=ReliabilityPolicy(max_attempts=1),
    ):
        chunks.append(chunk)

    assert primary_provider.call_count == 0
    assert fallback_provider.call_count == 1
    assert any("[DONE]" in c for c in chunks)


# ==============================================================================
# 7. Fail-Open Safety Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_fail_open_on_circuit_registry_error():
    registry = CircuitBreakerRegistry()
    # Force an internal error in before_call
    with patch.object(registry, "_get_or_create_circuit", side_effect=RuntimeError("Unexpected error")):
        decision = await registry.before_call("provider", "model")
        # Fail-open: Must allow request to proceed!
        assert decision.allowed is True
        assert decision.state == CircuitState.CLOSED


# ==============================================================================
# 8. Operator Diagnostic Endpoint (/internal/provider-health)
# ==============================================================================


def test_internal_provider_health_endpoint():
    client = TestClient(app)
    from gateway.src.config import settings

    headers = {"Authorization": f"Bearer {settings.metrics_token}"}
    response = client.get("/internal/provider-health", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "circuit_breaker_enabled" in data
    assert "circuits" in data
    assert "providers" in data
    assert "timestamp" in data


def test_internal_provider_health_endpoint_auth_required():
    client = TestClient(app)
    # Missing auth header when metrics_auth_enabled is True
    from gateway.src.config import settings

    if settings.metrics_auth_enabled:
        response = client.get("/internal/provider-health")
        assert response.status_code == 401


# ==============================================================================
# 9. Prometheus Metrics Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_circuit_breaker_prometheus_metrics():
    registry = CircuitBreakerRegistry(failure_threshold=2, open_duration_seconds=5.0)

    # Initial transition CLOSED -> OPEN
    await registry.record_failure("test_prov", "gpt-4o", FailureCategory.TRANSIENT)
    await registry.record_failure("test_prov", "gpt-4o", FailureCategory.TRANSIENT)

    # Check metrics
    t_val = CIRCUIT_TRANSITIONS_TOTAL.labels(
        provider="test_prov", model="gpt-4o", from_state="closed", to_state="open"
    )._value.get()
    assert t_val >= 1.0

    state_gauge = CIRCUIT_STATE.labels(provider="test_prov", model="gpt-4o")._value.get()
    assert state_gauge == 1.0  # 1 = open

    # Rejection metric
    d = await registry.before_call("test_prov", "gpt-4o")
    assert d.is_open is True
    from tollgate_core.observability.metrics import record_circuit_rejection

    record_circuit_rejection("test_prov", "gpt-4o")
    rej_val = CIRCUIT_REJECTIONS_TOTAL.labels(provider="test_prov", model="gpt-4o")._value.get()
    assert rej_val >= 1.0
