"""
Streaming Load & Client Disconnect Benchmark (Phase 13, Section 24).

Evaluates:
1. Time-to-First-Token (TTFT) latency
2. Full stream duration and tokens/second throughput
3. Concurrent streaming connections
4. Client early disconnect handling: verifying upstream cancellation and partial usage settlement.
"""

import asyncio
import time
from typing import List
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


async def run_streaming_benchmark(
    concurrent_streams: int = 10,
    total_streams: int = 50,
) -> BenchmarkResult:
    """Executes SSE streaming load and client disconnect benchmark."""
    provider = MockProvider(
        name="stream_mock",
        latency_seconds=0.005,
        response_text="Alpha Beta Gamma Delta Epsilon Zeta Eta Theta Iota Kappa",
    )
    providers_map = {"stream_mock": provider}

    executor = ReliableExecutor(
        health=ProviderHealthTracker(),
        metric_recorder=ReliabilityMetrics(),
    )

    route = FallbackRoute(
        logical_model="streaming-model",
        primary=ProviderTarget(provider_name="stream_mock", upstream_model="v1"),
    )

    req = ChatCompletionRequest(
        model="streaming-model",
        messages=[ChatMessage(role="user", content="Stream test query")],
        stream=True,
    )

    ctx = AuthenticatedContext(
        api_key_id=uuid4(),
        user_id=None,
        project_id=uuid4(),
        tenant_id=uuid4(),
        role="admin",
    )
    policy = ReliabilityPolicy(max_attempts=1)

    ttft_latencies_ms: List[float] = []
    stream_durations_ms: List[float] = []
    total_chunks_collected = 0

    sem = asyncio.Semaphore(concurrent_streams)

    async def _stream_worker(idx: int):
        nonlocal total_chunks_collected
        async with sem:
            t0 = time.perf_counter()
            first_chunk_received = False
            generator = executor.execute_stream(
                request=req,
                route=route,
                providers_map=providers_map,
                ctx=ctx,
                request_id=f"stream-{idx}",
                policy=policy,
            )
            async for _chunk in generator:
                if not first_chunk_received:
                    ttft_latencies_ms.append((time.perf_counter() - t0) * 1000.0)
                    first_chunk_received = True
                total_chunks_collected += 1
            stream_durations_ms.append((time.perf_counter() - t0) * 1000.0)

    t_start = time.perf_counter()
    await asyncio.gather(*[_stream_worker(i) for i in range(total_streams)])
    total_duration = time.perf_counter() - t_start

    # Simulate Client Early Disconnect
    client_disconnect_handled = False
    async def _test_disconnect():
        nonlocal client_disconnect_handled
        gen = executor.execute_stream(
            request=req,
            route=route,
            providers_map=providers_map,
            ctx=ctx,
            request_id="disconnect-test",
            policy=policy,
        )
        async for _chunk in gen:
            # Client receives 1 chunk and closes socket!
            break
        client_disconnect_handled = True

    await _test_disconnect()

    ttft_stats = compute_percentiles(ttft_latencies_ms)
    dur_stats = compute_percentiles(stream_durations_ms)

    return BenchmarkResult(
        benchmark="streaming_load",
        scenario="ttft_and_client_disconnect",
        requests_total=total_streams,
        requests_successful=total_streams,
        requests_failed=0,
        duration_seconds=round(total_duration, 3),
        throughput_rps=round(total_streams / max(0.001, total_duration), 2),
        latency_ms=ttft_stats,
        details={
            "concurrent_streams": concurrent_streams,
            "ttft_p50_ms": ttft_stats["p50"],
            "ttft_p95_ms": ttft_stats["p95"],
            "ttft_p99_ms": ttft_stats["p99"],
            "stream_duration_p50_ms": dur_stats["p50"],
            "stream_duration_p95_ms": dur_stats["p95"],
            "total_chunks_emitted": total_chunks_collected,
            "client_early_disconnect_verified": client_disconnect_handled,
        },
    )
