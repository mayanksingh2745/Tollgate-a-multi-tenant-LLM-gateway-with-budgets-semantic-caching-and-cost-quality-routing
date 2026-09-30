"""
Baseline Benchmark & Gateway Overhead Measurement (Phase 13, Sections 5 & 6).

Compares:
1. Direct MockProvider execution (Client -> MockProvider)
2. Tollgate ReliableExecutor execution (Client -> Tollgate Gateway -> MockProvider)

Calculates the exact microsecond/millisecond gateway overhead:
  Gateway Overhead = Tollgate Latency - Direct Provider Latency
"""

import asyncio
import time
from uuid import uuid4

from gateway.src.auth.context import AuthenticatedContext
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
    ChatCompletionRequest,
    ChatMessage,
)

from benchmarks.scenarios.base import BenchmarkResult, compute_percentiles


async def run_baseline_benchmark(
    concurrency: int = 1,
    request_count: int = 100,
    warmup_count: int = 20,
    provider_latency_seconds: float = 0.010, # 10ms simulated upstream
) -> BenchmarkResult:
    """Executes comparative benchmark to measure gateway latency overhead."""
    # Setup mock provider with deterministic latency
    provider = MockProvider(
        name="mock_baseline_provider",
        latency_seconds=provider_latency_seconds,
        response_text="Baseline benchmark response payload.",
    )
    providers_map = {"mock_baseline_provider": provider}

    executor = ReliableExecutor(
        health=ProviderHealthTracker(),
        metric_recorder=ReliabilityMetrics(),
    )

    route = FallbackRoute(
        logical_model="benchmark-model",
        primary=ProviderTarget(
            provider_name="mock_baseline_provider", upstream_model="mock-v1"
        ),
    )

    req = ChatCompletionRequest(
        model="benchmark-model",
        messages=[ChatMessage(role="user", content="Hello benchmark")],
    )

    ctx = AuthenticatedContext(
        api_key_id=uuid4(),
        user_id=None,
        project_id=uuid4(),
        tenant_id=uuid4(),
        role="admin",
    )
    policy = ReliabilityPolicy(max_attempts=1, provider_timeout_seconds=5.0)

    # 1. Warm-up
    for _ in range(warmup_count):
        await executor.execute_chat(
            request=req,
            route=route,
            providers_map=providers_map,
            ctx=ctx,
            request_id=f"warmup-{uuid4()}",
            policy=policy,
        )

    # 2. Measure Direct Provider Latency (Client -> Provider)
    direct_latencies_ms = []
    for _ in range(request_count):
        t0 = time.perf_counter()
        await provider.chat(req, "mock-v1", f"direct-{uuid4()}")
        direct_latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    # 3. Measure Tollgate Gateway Latency (Client -> Tollgate -> Provider)
    gateway_latencies_ms = []
    t_start = time.perf_counter()

    async def _send_gateway_req(idx: int):
        t0 = time.perf_counter()
        res, meta = await executor.execute_chat(
            request=req,
            route=route,
            providers_map=providers_map,
            ctx=ctx,
            request_id=f"bench-{idx}",
            policy=policy,
        )
        gateway_latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        return res

    # Run with specified concurrency
    sem = asyncio.Semaphore(concurrency)

    async def _sem_worker(idx: int):
        async with sem:
            return await _send_gateway_req(idx)

    tasks = [_sem_worker(i) for i in range(request_count)]
    await asyncio.gather(*tasks)
    total_duration = time.perf_counter() - t_start

    direct_stats = compute_percentiles(direct_latencies_ms)
    gateway_stats = compute_percentiles(gateway_latencies_ms)

    # Calculate overhead
    p50_overhead_ms = max(0.0, round(gateway_stats["p50"] - direct_stats["p50"], 3))
    p95_overhead_ms = max(0.0, round(gateway_stats["p95"] - direct_stats["p95"], 3))
    p99_overhead_ms = max(0.0, round(gateway_stats["p99"] - direct_stats["p99"], 3))
    overhead_pct = round((p50_overhead_ms / max(0.001, direct_stats["p50"])) * 100, 2)

    return BenchmarkResult(
        benchmark="gateway_baseline",
        scenario="overhead_comparison",
        requests_total=request_count,
        requests_successful=len(gateway_latencies_ms),
        requests_failed=request_count - len(gateway_latencies_ms),
        duration_seconds=round(total_duration, 4),
        throughput_rps=round(request_count / total_duration, 2),
        latency_ms=gateway_stats,
        details={
            "concurrency": concurrency,
            "simulated_upstream_latency_ms": provider_latency_seconds * 1000.0,
            "direct_provider_latency_ms": direct_stats,
            "gateway_latency_ms": gateway_stats,
            "overhead_ms": {
                "p50": p50_overhead_ms,
                "p95": p95_overhead_ms,
                "p99": p99_overhead_ms,
            },
            "overhead_percentage_p50": overhead_pct,
        },
    )
