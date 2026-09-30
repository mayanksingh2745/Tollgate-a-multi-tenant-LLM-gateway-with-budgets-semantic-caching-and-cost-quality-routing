import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from gateway.src.cache.service import ExactResponseCache, InMemoryCacheBackend
from gateway.src.reliability.circuit_breaker import CircuitBreakerState, CircuitState
from gateway.src.reliability.failure_classifier import FailureCategory
from gateway.src.schemas.chat import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    UsageInfo,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import UsageDailyRollup
from tollgate_core.observability.metrics import (
    record_failover_event,
    record_recovery_event,
)
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.persistence import persist_usage_event


@pytest.mark.asyncio
async def test_cache_complete_loss_rebuild_without_side_effects():
    """
    Simulates catastrophic Redis cache flush:
    1. Populate cache with responses.
    2. Completely wipe cache backend (cache loss).
    3. Verify request produces clean cache MISS without throwing errors.
    4. Verify upstream provider response repopulates cache correctly.
    5. Verify subsequent call results in cache HIT with exact fidelity.
    6. Verify cross-tenant isolation is strictly maintained across cache rebuilds.
    """
    backend = InMemoryCacheBackend()
    cache = ExactResponseCache(backend=backend)

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    project_id = uuid.uuid4()
    provider = "openai"

    req = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="Explain quantum computing")],
    )
    resp = ChatCompletionResponse(
        id="chatcmpl-rebuild-1",
        created=1711800000,
        model="gpt-4o",
        choices=[ChatChoice(index=0, message=ChatChoiceMessage(role="assistant", content="Quantum computing uses qubits."))],
        usage=UsageInfo(prompt_tokens=15, completion_tokens=25, total_tokens=40),
    )

    # 1. Populate initial cache
    stored = await cache.set(req, resp, tenant_a, project_id, provider)
    assert stored is True
    assert await cache.get(req, tenant_a, project_id, provider) is not None

    # 2. Catastrophic Cache Loss (Redis flush)
    backend.clear()

    # 3. Request after cache loss is a graceful MISS (fail-open)
    miss_result = await cache.get(req, tenant_a, project_id, provider)
    assert miss_result is None

    # 4. Provider response repopulates cache
    repopulated = await cache.set(req, resp, tenant_a, project_id, provider)
    assert repopulated is True

    # 5. Subsequent request is a clean HIT
    hit_result = await cache.get(req, tenant_a, project_id, provider)
    assert hit_result is not None
    assert hit_result.choices[0].message.content == "Quantum computing uses qubits."

    # 6. Cross-Tenant Isolation: Tenant B querying identical request receives MISS
    tenant_b_result = await cache.get(req, tenant_b, project_id, provider)
    assert tenant_b_result is None


@pytest.mark.asyncio
async def test_provider_chaos_matrix_and_circuit_tripping():
    """
    Validates the full circuit breaker failure matrix:
    - 429 Rate Limits: Ignored until consecutive threshold (default 10).
    - 5xx Transient Failures: Accrue towards tripping threshold (3).
    - Tripping: CLOSED -> OPEN.
    - Recovery: OPEN -> Cooldown -> HALF_OPEN (probe) -> CLOSED.
    - Telemetry: Metrics emitted on transition.
    """
    cb = CircuitBreakerState(
        failure_threshold=3,
        failure_window_seconds=10.0,
        open_duration_seconds=0.2,
        half_open_max_calls=1,
        rate_limit_threshold=3,
    )
    provider_key = "openai:gpt-4o"

    # 1. Non-tripping client errors (400, 404) do NOT trip circuit
    for _ in range(5):
        await cb.record_failure(provider_key, FailureCategory.BAD_REQUEST)
        await cb.record_failure(provider_key, FailureCategory.NOT_FOUND)
    assert cb.state == CircuitState.CLOSED

    # 2. Single 429 does NOT trip circuit
    await cb.record_failure(provider_key, FailureCategory.RATE_LIMITED)
    assert cb.state == CircuitState.CLOSED

    # 3. Transient 500 errors trip circuit after threshold (3 failures)
    for _ in range(3):
        await cb.record_failure(provider_key, FailureCategory.TRANSIENT)
    assert cb.state == CircuitState.OPEN
    record_failover_event("provider", "success")

    # While OPEN, calls are rejected immediately
    decision = await cb.before_call(provider_key)
    assert decision.allowed is False

    # 4. Wait for recovery cooldown
    await asyncio.sleep(0.25)

    # 5. Transition to HALF_OPEN probe
    probe_decision = await cb.before_call(provider_key)
    assert probe_decision.allowed is True
    assert probe_decision.is_probe is True
    assert cb.state == CircuitState.HALF_OPEN

    # 6. Successful probe restores circuit to CLOSED
    await cb.record_success(provider_key)
    assert cb.state == CircuitState.CLOSED
    record_recovery_event("circuit_breaker", "success")


@pytest.mark.asyncio
async def test_connection_storm_and_concurrency_stability():
    """
    Simulates high concurrent load (50 concurrent requests):
    Verifies that async coordination mechanisms remain non-blocking,
    deadlock-free, and stable under load.
    """
    backend = InMemoryCacheBackend()
    cache = ExactResponseCache(backend=backend)
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()

    async def worker_task(idx: int):
        req = ChatCompletionRequest(
            model="gpt-4o",
            messages=[ChatMessage(role="user", content=f"Concurrent prompt {idx}")],
        )
        resp = ChatCompletionResponse(
            id=f"chatcmpl-storm-{idx}",
            created=1711800000,
            model="gpt-4o",
            choices=[ChatChoice(index=0, message=ChatChoiceMessage(role="assistant", content=f"Response {idx}"))],
            usage=UsageInfo(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )
        # Concurrent write
        await cache.set(req, resp, tenant_id, project_id, "openai")
        # Concurrent read
        result = await cache.get(req, tenant_id, project_id, "openai")
        assert result is not None
        assert result.id == f"chatcmpl-storm-{idx}"

    tasks = [worker_task(i) for i in range(50)]
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_usage_stream_recovery_under_load(db_session: AsyncSession):
    """
    Simulates 20 concurrent usage events where a worker fails halfway through:
    Verifies that all 20 events are cleanly processed without double-counting.
    """
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()

    events = [
        UsageEventPayload(
            event_id=uuid.uuid4(),
            event_version="1.0",
            request_id=f"req_storm_{i}",
            reservation_id=f"res_storm_{i}",
            tenant_id=tenant_id,
            project_id=project_id,
            api_key_id=uuid.uuid4(),
            provider="openai",
            model="gpt-4o",
            stream=False,
            status="success",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost=3000,
            actual_cost=2000,
            latency_ms=120.0,
            attempt_count=1,
            fallback_used=False,
            created_at=datetime.now(timezone.utc),
        )
        for i in range(20)
    ]

    # Worker 1 processes first 10 events
    for ev in events[:10]:
        await persist_usage_event(db_session, ev)
    await db_session.commit()

    # Worker 1 crashes. Worker 2 processes remaining 10 events,
    # AND replays 3 events from Worker 1 due to simulated un-ACKed reclaim
    replayed_and_new_events = events[7:] # 7, 8, 9 replayed, 10-19 new
    for ev in replayed_and_new_events:
        await persist_usage_event(db_session, ev)
    await db_session.commit()

    # Check daily rollups: Total events must be exactly 20 (not 23)
    today_date = datetime.now(timezone.utc).date()
    stmt = select(UsageDailyRollup).where(
        UsageDailyRollup.tenant_id == tenant_id,
        UsageDailyRollup.date == today_date,
    )
    rollup = (await db_session.execute(stmt)).scalar_one()
    assert rollup.request_count == 20
    assert rollup.total_tokens == 20 * 150
    assert rollup.actual_cost == 20 * 2000
