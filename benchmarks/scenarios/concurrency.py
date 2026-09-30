"""
Throughput & Concurrency Scaling Benchmark (Phase 13, Section 7).

Evaluates gateway behavior under escalating concurrency levels [1, 5, 10, 25, 50, 100].
Calculates RPS, p50, p95, p99, error rates, and identifies the sustainable saturation knee.
"""

import asyncio
import time
from typing import Any, Dict, List
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


async def run_concurrency_benchmark(
    concurrency_levels: List[int] = None,
    requests_per_level: int = 150,
    upstream_latency_seconds: float = 0.005, # 5ms fast mock
    max_p95_sla_ms: float = 50.0,
    max_error_rate: float = 0.01,
) -> BenchmarkResult:
    """Executes concurrency ladder benchmark."""
    if concurrency_levels is None:
        concurrency_levels = [1, 5, 10, 25, 50, 100]
    provider = MockProvider(
        name="concurrency_mock",
        latency_seconds=upstream_latency_seconds,
    )
    providers_map = {"concurrency_mock": provider}

    executor = ReliableExecutor(
        health=ProviderHealthTracker(),
        metric_recorder=ReliabilityMetrics(),
    )

    route = FallbackRoute(
        logical_model="concurrency-model",
        primary=ProviderTarget(
            provider_name="concurrency_mock", upstream_model="mock-v1"
        ),
    )

    req = ChatCompletionRequest(
        model="concurrency-model",
        messages=[ChatMessage(role="user", content="Concurrency test ping")],
    )

    ctx = AuthenticatedContext(
        api_key_id=uuid4(),
        user_id=None,
        project_id=uuid4(),
        tenant_id=uuid4(),
        role="admin",
    )
    policy = ReliabilityPolicy(max_attempts=1, provider_timeout_seconds=5.0)

    # Ladder results
    ladder_results: Dict[str, Any] = {}
    sustainable_rps = 0.0
    max_sustainable_concurrency = 1

    total_requests_all = 0
    total_successful_all = 0
    total_duration_all = 0.0
    all_latencies: List[float] = []

    for c in concurrency_levels:
        sem = asyncio.Semaphore(c)
        latencies_ms: List[float] = []
        errors = 0

        async def _worker(idx: int, s=sem, c_val=c, l_ms=latencies_ms):
            nonlocal errors
            async with s:
                t0 = time.perf_counter()
                try:
                    res, meta = await executor.execute_chat(
                        request=req,
                        route=route,
                        providers_map=providers_map,
                        ctx=ctx,
                        request_id=f"c-{c_val}-{idx}",
                        policy=policy,
                    )
                    l_ms.append((time.perf_counter() - t0) * 1000.0)
                except Exception:
                    errors += 1

        t_start = time.perf_counter()
        tasks = [_worker(i) for i in range(requests_per_level)]
        await asyncio.gather(*tasks)
        level_duration = time.perf_counter() - t_start

        level_stats = compute_percentiles(latencies_ms)
        level_rps = round(len(latencies_ms) / max(0.001, level_duration), 2)
        level_error_rate = round(errors / requests_per_level, 4)

        # Check saturation criterion: p95 within SLA AND error rate <= threshold
        is_sustainable = (level_stats["p95"] <= max_p95_sla_ms) and (level_error_rate <= max_error_rate)
        if is_sustainable and level_rps > sustainable_rps:
            sustainable_rps = level_rps
            max_sustainable_concurrency = c

        ladder_results[str(c)] = {
            "concurrency": c,
            "requests": requests_per_level,
            "successful": len(latencies_ms),
            "errors": errors,
            "error_rate": level_error_rate,
            "duration_seconds": round(level_duration, 3),
            "rps": level_rps,
            "p50_ms": level_stats["p50"],
            "p95_ms": level_stats["p95"],
            "p99_ms": level_stats["p99"],
            "is_sustainable": is_sustainable,
        }

        total_requests_all += requests_per_level
        total_successful_all += len(latencies_ms)
        total_duration_all += level_duration
        all_latencies.extend(latencies_ms)

    return BenchmarkResult(
        benchmark="concurrency_scaling",
        scenario="concurrency_ladder",
        requests_total=total_requests_all,
        requests_successful=total_successful_all,
        requests_failed=total_requests_all - total_successful_all,
        duration_seconds=round(total_duration_all, 3),
        throughput_rps=round(total_successful_all / max(0.001, total_duration_all), 2),
        latency_ms=compute_percentiles(all_latencies),
        details={
            "levels_evaluated": concurrency_levels,
            "sustainable_rps": sustainable_rps,
            "max_sustainable_concurrency": max_sustainable_concurrency,
            "saturation_criteria": {
                "max_p95_sla_ms": max_p95_sla_ms,
                "max_error_rate": max_error_rate,
            },
            "ladder": ladder_results,
        },
    )
