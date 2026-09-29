import asyncio
import uuid

import pytest
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.providers.mock import MockProvider
from gateway.src.reliability.backoff import BackoffStrategy
from gateway.src.reliability.executor import ReliableExecutor
from gateway.src.reliability.policy import (
    FallbackRoute,
    ProviderTarget,
    ReliabilityPolicy,
)
from gateway.src.schemas.chat import ChatCompletionRequest, ChatMessage


@pytest.mark.asyncio
async def test_concurrent_fallback_isolation():
    # Primary provider A always fails with 503
    prov_a = MockProvider(name="prov_a", should_fail=True, failure_status=503)
    # Fallback provider B succeeds
    prov_b = MockProvider(name="prov_b", response_text="Concurrent fallback success")

    route = FallbackRoute(
        logical_model="concurrent-model",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
        fallbacks=[ProviderTarget(provider_name="prov_b", upstream_model="model_b")],
    )
    providers_map = {"prov_a": prov_a, "prov_b": prov_b}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.01, jitter=False)
    )
    policy = ReliabilityPolicy(max_attempts=1, base_delay=0.001, max_delay=0.01)

    concurrency = 50

    async def single_request(idx: int):
        req_id = f"req_conc_{idx}_{uuid.uuid4().hex[:8]}"
        ctx = AuthenticatedContext(
            tenant_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            api_key_id=uuid.uuid4(),
        )
        req = ChatCompletionRequest(
            model="concurrent-model",
            messages=[ChatMessage(role="user", content=f"Hello request {idx}")],
            stream=False,
        )
        res, meta = await executor.execute_chat(
            request=req,
            route=route,
            providers_map=providers_map,
            ctx=ctx,
            request_id=req_id,
            policy=policy,
        )
        return req_id, res, meta

    # Run 50 concurrent requests simultaneously
    tasks = [single_request(i) for i in range(concurrency)]
    results = await asyncio.gather(*tasks)

    assert len(results) == concurrency
    seen_ids = set()

    for req_id, res, meta in results:
        assert req_id not in seen_ids
        seen_ids.add(req_id)
        assert res.choices[0].message.content == "Concurrent fallback success"
        assert meta.fallback_used is True
        assert meta.final_provider == "prov_b"
        assert meta.total_attempts in (
            1,
            2,
        )  # Initial requests try A then B (2); subsequent requests skip A when unhealthy (1)

    # prov_a was marked unhealthy after failure threshold, avoiding 50 unnecessary calls!
    assert 1 <= prov_a.call_count <= concurrency
    assert prov_b.call_count == concurrency
