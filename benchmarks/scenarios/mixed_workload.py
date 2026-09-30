"""
Mixed Realistic Workload Benchmark (Phase 13, Section 25).

Simulates production-like traffic combining:
1. Short vs long prompts
2. Streaming vs non-streaming requests
3. Exact-cache hits vs misses
4. Cheap vs strong router classifications
5. Occasional transient upstream failures with retries and failover.
"""

import asyncio
import time
from typing import List
from uuid import uuid4

from gateway.src.auth.context import AuthenticatedContext
from gateway.src.cache.service import ExactResponseCache, InMemoryCacheBackend
from gateway.src.providers.mock import MockProvider
from gateway.src.reliability.executor import ReliableExecutor
from gateway.src.reliability.health import ProviderHealthTracker
from gateway.src.reliability.metrics import ReliabilityMetrics
from gateway.src.reliability.policy import (
    FallbackRoute,
    ProviderTarget,
    ReliabilityPolicy,
)
from gateway.src.schemas.chat import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    UsageInfo,
)

from benchmarks.scenarios.base import BenchmarkResult, compute_percentiles


async def run_mixed_workload_benchmark(
    request_count: int = 150,
    concurrency: int = 10,
) -> BenchmarkResult:
    """Executes a realistic mixed workload simulation."""
    cache = ExactResponseCache(backend=InMemoryCacheBackend())

    prov_primary = MockProvider(name="mixed_primary", latency_seconds=0.005)
    prov_fallback = MockProvider(name="mixed_fallback", latency_seconds=0.005, response_text="Fallback recovered.")
    providers_map = {
        "mixed_primary": prov_primary,
        "mixed_fallback": prov_fallback,
    }

    executor = ReliableExecutor(
        health=ProviderHealthTracker(),
        metric_recorder=ReliabilityMetrics(),
    )

    route = FallbackRoute(
        logical_model="mixed-model",
        primary=ProviderTarget(provider_name="mixed_primary", upstream_model="v1"),
        fallbacks=[ProviderTarget(provider_name="mixed_fallback", upstream_model="v2")],
    )

    ctx = AuthenticatedContext(
        api_key_id=uuid4(),
        user_id=None,
        project_id=uuid4(),
        tenant_id=uuid4(),
        role="admin",
    )
    policy = ReliabilityPolicy(max_attempts=2, provider_timeout_seconds=5.0)

    # Pre-populate exact cache for popular queries
    popular_query = "What is the status of the cluster?"
    pop_req = ChatCompletionRequest(model="mixed-model", messages=[ChatMessage(role="user", content=popular_query)])
    await cache.set(
        request=pop_req,
        response=ChatCompletionResponse(
            id=f"resp-{uuid4()}",
            object="chat.completion",
            created=int(time.time()),
            model="mixed-model",
            choices=[ChatChoice(index=0, message=ChatChoiceMessage(role="assistant", content="Cluster operational."))],
            usage=UsageInfo(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        ),
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        provider="openai",
    )

    latencies_ms: List[float] = []
    cache_hits = 0
    cache_misses = 0
    streams_handled = 0
    fallbacks_triggered = 0

    sem = asyncio.Semaphore(concurrency)

    async def _send_item(i: int):
        nonlocal cache_hits, cache_misses, streams_handled, fallbacks_triggered
        async with sem:
            t0 = time.perf_counter()

            # 1. 20% of traffic is the popular cached query
            if (i % 5) == 0:
                cached = await cache.get(
                    request=pop_req,
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    provider="openai",
                )
                if cached:
                    cache_hits += 1
                    latencies_ms.append((time.perf_counter() - t0) * 1000.0)
                    return

            cache_misses += 1

            # 2. 30% of remaining traffic is streaming
            is_stream = (i % 3) == 0
            if is_stream:
                streams_handled += 1
                stream_req = ChatCompletionRequest(
                    model="mixed-model",
                    messages=[ChatMessage(role="user", content=f"Stream task {i}")],
                    stream=True,
                )
                gen = executor.execute_stream(
                    request=stream_req,
                    route=route,
                    providers_map=providers_map,
                    ctx=ctx,
                    request_id=f"mix-str-{i}",
                    policy=policy,
                )
                async for _ in gen:
                    pass
                latencies_ms.append((time.perf_counter() - t0) * 1000.0)
                return

            # 3. 5% simulates transient primary failure needing fallback
            if (i % 20) == 19:
                prov_primary.should_fail = True
                prov_primary.failure_status = 503
                fallbacks_triggered += 1
            else:
                prov_primary.should_fail = False

            # Non-streaming prompt
            content = "Short query" if (i % 2 == 0) else ("Long prompt with detailed context " * 20)
            chat_req = ChatCompletionRequest(
                model="mixed-model",
                messages=[ChatMessage(role="user", content=content)],
            )
            res, meta = await executor.execute_chat(
                request=chat_req,
                route=route,
                providers_map=providers_map,
                ctx=ctx,
                request_id=f"mix-chat-{i}",
                policy=policy,
            )
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    t_start = time.perf_counter()
    await asyncio.gather(*[_send_item(i) for i in range(request_count)])
    total_duration = time.perf_counter() - t_start

    stats = compute_percentiles(latencies_ms)
    throughput = round(len(latencies_ms) / max(0.001, total_duration), 2)

    return BenchmarkResult(
        benchmark="mixed_workload",
        scenario="realistic_traffic_blend",
        requests_total=request_count,
        requests_successful=len(latencies_ms),
        requests_failed=request_count - len(latencies_ms),
        duration_seconds=round(total_duration, 3),
        throughput_rps=throughput,
        latency_ms=stats,
        details={
            "concurrency": concurrency,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "cache_hit_rate": round(cache_hits / request_count, 3),
            "streaming_requests": streams_handled,
            "fallbacks_triggered": fallbacks_triggered,
            "p50_ms": stats["p50"],
            "p95_ms": stats["p95"],
            "p99_ms": stats["p99"],
        },
    )
