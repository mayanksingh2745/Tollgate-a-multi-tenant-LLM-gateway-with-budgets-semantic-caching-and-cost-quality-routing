import uuid

import pytest
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.providers.mock import MockProvider
from gateway.src.reliability.executor import ReliableExecutor
from gateway.src.reliability.policy import (
    FallbackRoute,
    ProviderTarget,
    ReliabilityPolicy,
)
from gateway.src.schemas.chat import ChatCompletionRequest
from httpx import AsyncClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from tollgate_core.observability import reset_tracer_provider
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.consumer import UsageWorkerConsumer


@pytest.fixture
def memory_exporter():
    """Sets up an in-memory span exporter for OpenTelemetry tracing tests."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    reset_tracer_provider(provider)
    yield exporter
    reset_tracer_provider(None)


@pytest.fixture
async def setup_tenant_and_key(async_client: AsyncClient):
    """Helper fixture to create a valid tenant, project, and API key."""
    t_res = await async_client.post(
        "/api/v1/tenants", json={"name": "Otel Co", "slug": f"otel-co-{uuid.uuid4().hex[:6]}"}
    )
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects", json={"name": "Otel Core", "slug": "otel-core"}
    )
    project_id = p_res.json()["id"]

    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "Otel Dev Key"}
    )
    key_data = k_res.json()
    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "api_key_id": key_data["id"],
        "raw_key": key_data["key"],
        "headers": {"Authorization": f"Bearer {key_data['key']}"},
    }


@pytest.mark.asyncio
async def test_request_creates_trace_and_spans(
    async_client: AsyncClient, setup_tenant_and_key, memory_exporter
):
    """Verifies that a normal chat completion request generates expected distributed traces and spans."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello OpenTelemetry"}],
        "temperature": 0.7,
    }
    res = await async_client.post(
        "/v1/chat/completions",
        headers=setup_tenant_and_key["headers"],
        json=payload,
    )
    assert res.status_code == 200

    # Verify response headers
    assert "X-Request-ID" in res.headers
    assert "X-Trace-ID" in res.headers
    assert "traceparent" in res.headers

    spans = memory_exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    # Verify critical span names exist
    assert "gateway.request" in span_names
    assert "authenticate" in span_names
    assert "rate_limit" in span_names
    assert "cache.lookup" in span_names
    assert "router.decision" in span_names
    assert "budget.reserve" in span_names
    assert "provider.request" in span_names
    assert "provider.attempt" in span_names
    assert "budget.settle" in span_names
    assert "cache.write" in span_names
    assert "usage.publish" in span_names

    # Check root gateway.request span attributes
    root_span = next(s for s in spans if s.name == "gateway.request")
    assert root_span.attributes["http.request.method"] == "POST"
    assert root_span.attributes["http.route"] == "/v1/chat/completions"
    assert root_span.attributes["http.response.status_code"] == 200
    assert root_span.attributes["tollgate.tenant_id"] == setup_tenant_and_key["tenant_id"]
    assert root_span.attributes["tollgate.project_id"] == setup_tenant_and_key["project_id"]
    assert root_span.attributes["tollgate.request_id"] == res.headers["X-Request-ID"]

    # Verify trace ID matches response header
    assert f"{root_span.context.trace_id:032x}" == res.headers["X-Trace-ID"]


@pytest.mark.asyncio
async def test_w3c_traceparent_propagation(
    async_client: AsyncClient, setup_tenant_and_key, memory_exporter
):
    """Verifies that incoming W3C traceparent headers propagate context into root span and child spans."""
    in_trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    in_parent_span_id = "00f067aa0ba902b7"
    w3c_traceparent = f"00-{in_trace_id}-{in_parent_span_id}-01"

    headers = {
        **setup_tenant_and_key["headers"],
        "traceparent": w3c_traceparent,
    }
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "W3C Propagation test"}],
    }

    res = await async_client.post("/v1/chat/completions", headers=headers, json=payload)
    assert res.status_code == 200

    spans = memory_exporter.get_finished_spans()
    root_span = next(s for s in spans if s.name == "gateway.request")

    # The trace ID should match the incoming W3C traceparent trace_id!
    assert f"{root_span.context.trace_id:032x}" == in_trace_id
    assert root_span.parent.span_id == int(in_parent_span_id, 16)
    assert res.headers["X-Trace-ID"] == in_trace_id
    assert in_trace_id in res.headers["traceparent"]


@pytest.mark.asyncio
async def test_cache_hit_visibility_and_no_provider_span(
    async_client: AsyncClient, setup_tenant_and_key, memory_exporter
):
    """Verifies that a cache hit creates a cache.lookup HIT span and bypasses provider spans."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": f"Cache Hit Observation {uuid.uuid4().hex}"}],
        "temperature": 0.0,
    }

    # Request 1: cache miss
    res1 = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res1.status_code == 200

    # Clear spans to inspect only the second request
    memory_exporter.clear()

    # Request 2: cache hit
    res2 = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res2.status_code == 200
    assert res2.headers.get("X-Tollgate-Cache") == "HIT"

    spans2 = memory_exporter.get_finished_spans()
    span_names2 = [s.name for s in spans2]

    # Verify cache.lookup was recorded with hit=True
    assert "cache.lookup" in span_names2
    cache_span = next(s for s in spans2 if s.name == "cache.lookup")
    assert cache_span.attributes["cache.hit"] is True
    assert cache_span.attributes["cache.type"] == "exact"

    # CRITICAL: Verify NO provider span was created on cache hit!
    assert "provider.request" not in span_names2
    assert "provider.attempt" not in span_names2


@pytest.mark.asyncio
async def test_streaming_trace_captures_ttft_and_no_per_chunk_spans(
    async_client: AsyncClient, setup_tenant_and_key, memory_exporter
):
    """Verifies that streaming completions capture time to first token without spamming chunk spans."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Stream trace test"}],
        "stream": True,
    }
    res = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    stream_content = await res.aread()
    assert b"[DONE]" in stream_content

    spans = memory_exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    assert "provider.request" in span_names
    assert "provider.attempt" in span_names

    prov_span = next(s for s in spans if s.name == "provider.request")
    assert prov_span.attributes["tollgate.stream"] is True

    attempt_span = next(s for s in spans if s.name == "provider.attempt")
    assert "tollgate.time_to_first_token_ms" in attempt_span.attributes
    assert "tollgate.stream_duration_ms" in attempt_span.attributes
    assert "tollgate.chunks_emitted" in attempt_span.attributes
    assert attempt_span.attributes["status"] == "success"

    # Ensure no spans with 'chunk' exist
    assert not any("chunk" in name.lower() for name in span_names)


@pytest.mark.asyncio
async def test_retry_and_fallback_tracing(memory_exporter):
    """Verifies provider attempt failures, retries, and fallbacks are observable in trace spans."""
    executor = ReliableExecutor()

    # Create a failing primary provider and a succeeding fallback provider
    fail_provider = MockProvider(name="mock-primary", should_fail=True, failure_status=429)
    succ_provider = MockProvider(name="mock-backup", should_fail=False)

    providers_map = {
        "mock-primary": fail_provider,
        "mock-backup": succ_provider,
    }

    route = FallbackRoute(
        logical_model="mock-model",
        primary=ProviderTarget(provider_name="mock-primary", upstream_model="primary-model"),
        fallbacks=[ProviderTarget(provider_name="mock-backup", upstream_model="backup-model")],
    )

    req = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "Test failover"}],
    )
    ctx = AuthenticatedContext(
        api_key_id=uuid.uuid4(),
        user_id=None,
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role="admin",
    )

    policy = ReliabilityPolicy(
        max_attempts=2,
        base_delay=0.01,
        max_delay=0.05,
        provider_timeout_seconds=2.0,
        overall_timeout_seconds=5.0,
    )

    res, meta = await executor.execute_chat(
        request=req,
        route=route,
        providers_map=providers_map,
        ctx=ctx,
        request_id="req_test_failover",
        policy=policy,
    )
    assert meta.final_provider == "mock-backup"
    assert meta.fallback_used is True

    spans = memory_exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    # Verify attempt, retry, and fallback spans
    assert "provider.request" in span_names
    assert "provider.attempt" in span_names
    assert "provider.retry" in span_names
    assert "provider.fallback" in span_names

    fallback_span = next(s for s in spans if s.name == "provider.fallback")
    assert fallback_span.attributes["tollgate.provider.fallback"] is True
    assert fallback_span.attributes["tollgate.fallback.from_provider"] == "mock-primary"
    assert fallback_span.attributes["tollgate.fallback.to_provider"] == "mock-backup"


@pytest.mark.asyncio
async def test_worker_processing_is_traceable(memory_exporter, db_session):
    """Verifies that the async usage worker consumer establishes a linked trace context."""
    from unittest.mock import AsyncMock

    mock_redis = AsyncMock()
    mock_redis.xack = AsyncMock()

    # Session factory returning the db_session
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_session_factory():
        yield db_session

    consumer = UsageWorkerConsumer(
        redis_client=mock_redis,
        session_factory=mock_session_factory,
    )

    in_trace_id = "5cf92f3577b34da6a3ce929d0e0e4736"
    in_span_id = "11f067aa0ba902b7"
    w3c_tp = f"00-{in_trace_id}-{in_span_id}-01"

    t_id = uuid.uuid4()
    p_id = uuid.uuid4()

    from tollgate_core.models import Project, Tenant

    await db_session.execute(
        Tenant.__table__.insert().values(
            id=t_id, name="Trace Tenant", slug=f"tt-{uuid.uuid4().hex[:6]}"
        )
    )
    await db_session.execute(
        Project.__table__.insert().values(id=p_id, tenant_id=t_id, name="Trace Project", slug="tp")
    )
    await db_session.commit()

    event = UsageEventPayload(
        request_id="req_worker_trace",
        reservation_id="req_worker_trace",
        tenant_id=t_id,
        project_id=p_id,
        api_key_id=uuid.uuid4(),
        provider="mock",
        model="mock-model",
        status="success",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        estimated_cost=1000,
        actual_cost=500,
        latency_ms=120.0,
        traceparent=w3c_tp,
        trace_id=in_trace_id,
        span_id=in_span_id,
    )

    ok = await consumer.process_message("msg_trace_1", event.to_stream_entry())
    assert ok is True

    spans = memory_exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    assert "usage.process" in span_names
    assert "usage.persist" in span_names
    assert "usage.rollup" in span_names

    proc_span = next(s for s in spans if s.name == "usage.process")
    # Verify usage.process extracted the incoming trace ID
    assert f"{proc_span.context.trace_id:032x}" == in_trace_id
    assert proc_span.parent.span_id == int(in_span_id, 16)
    assert proc_span.attributes["tollgate.request_id"] == "req_worker_trace"
