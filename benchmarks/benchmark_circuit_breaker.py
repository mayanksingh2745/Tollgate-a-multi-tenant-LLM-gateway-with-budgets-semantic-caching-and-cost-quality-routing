"""
Benchmark suite for Tollgate Circuit Breaker (Phase 12).

Measures:
1. In-memory check overhead for CLOSED circuit (microseconds per call)
2. Fast rejection latency for OPEN circuit (comparison against upstream timeout)
3. Concurrent contention latency under 100 concurrent coroutines
4. Throughput (operations per second)
"""

import asyncio
import statistics
import sys
import time
from pathlib import Path
from typing import List

root_dir = Path(__file__).resolve().parents[1]
core_src = root_dir / "packages" / "core" / "src"
apps_dir = root_dir / "apps"

for p in [str(root_dir), str(apps_dir), str(core_src)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from gateway.src.reliability.circuit_breaker import (
    CircuitBreakerRegistry,
)
from gateway.src.reliability.failure_classifier import FailureCategory


async def benchmark_closed_overhead(iterations: int = 10000) -> dict:
    """Measures microsecond latency of before_call on a healthy (CLOSED) circuit."""
    registry = CircuitBreakerRegistry(enabled=True)
    # Warmup
    for _ in range(100):
        await registry.before_call("openai", "gpt-4o")

    latencies_us: List[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        decision = await registry.before_call("openai", "gpt-4o")
        t1 = time.perf_counter()
        assert decision.allowed is True
        latencies_us.append((t1 - t0) * 1_000_000.0)

    latencies_us.sort()
    return {
        "iterations": iterations,
        "mean_us": statistics.mean(latencies_us),
        "median_us": statistics.median(latencies_us),
        "p95_us": latencies_us[int(len(latencies_us) * 0.95)],
        "p99_us": latencies_us[int(len(latencies_us) * 0.99)],
        "ops_per_sec": iterations / (sum(latencies_us) / 1_000_000.0),
    }


async def benchmark_open_rejection(iterations: int = 10000) -> dict:
    """Measures fast-rejection microsecond latency on an OPEN circuit."""
    registry = CircuitBreakerRegistry(enabled=True, failure_threshold=2)
    # Trip circuit to OPEN
    await registry.record_failure("anthropic", "claude-3-5-sonnet", FailureCategory.TRANSIENT)
    await registry.record_failure("anthropic", "claude-3-5-sonnet", FailureCategory.TRANSIENT)

    latencies_us: List[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        decision = await registry.before_call("anthropic", "claude-3-5-sonnet")
        t1 = time.perf_counter()
        assert decision.allowed is False
        latencies_us.append((t1 - t0) * 1_000_000.0)

    latencies_us.sort()
    return {
        "iterations": iterations,
        "mean_us": statistics.mean(latencies_us),
        "median_us": statistics.median(latencies_us),
        "p95_us": latencies_us[int(len(latencies_us) * 0.95)],
        "p99_us": latencies_us[int(len(latencies_us) * 0.99)],
        "ops_per_sec": iterations / (sum(latencies_us) / 1_000_000.0),
    }


async def benchmark_concurrent_contention(concurrency: int = 100, calls_per_worker: int = 200) -> dict:
    """Measures latency under heavy asyncio lock contention across multiple coroutines."""
    registry = CircuitBreakerRegistry(enabled=True)

    latencies_us: List[float] = []

    async def worker():
        worker_latencies = []
        for _ in range(calls_per_worker):
            t0 = time.perf_counter()
            d = await registry.before_call("openai", "gpt-4o")
            t1 = time.perf_counter()
            assert d.allowed is True
            worker_latencies.append((t1 - t0) * 1_000_000.0)
        return worker_latencies

    t_start = time.perf_counter()
    results = await asyncio.gather(*[worker() for _ in range(concurrency)])
    t_total = time.perf_counter() - t_start

    for r in results:
        latencies_us.extend(r)

    latencies_us.sort()
    total_calls = concurrency * calls_per_worker
    return {
        "concurrency": concurrency,
        "total_calls": total_calls,
        "total_time_s": t_total,
        "mean_us": statistics.mean(latencies_us),
        "median_us": statistics.median(latencies_us),
        "p95_us": latencies_us[int(len(latencies_us) * 0.95)],
        "p99_us": latencies_us[int(len(latencies_us) * 0.99)],
        "ops_per_sec": total_calls / t_total,
    }


async def main():
    print("=" * 60)
    print("TOLLGATE CIRCUIT BREAKER BENCHMARK SUITE (PHASE 12)")
    print("=" * 60)

    print("\n1. Measuring CLOSED Circuit Check Overhead (10,000 iterations)...")
    closed_res = await benchmark_closed_overhead(10000)
    print(f"   Mean:   {closed_res['mean_us']:.2f} µs")
    print(f"   Median: {closed_res['median_us']:.2f} µs")
    print(f"   p95:    {closed_res['p95_us']:.2f} µs")
    print(f"   p99:    {closed_res['p99_us']:.2f} µs")
    print(f"   Throughput: {closed_res['ops_per_sec']:,.0f} ops/sec")

    print("\n2. Measuring OPEN Circuit Fast-Rejection (10,000 iterations)...")
    open_res = await benchmark_open_rejection(10000)
    print(f"   Mean:   {open_res['mean_us']:.2f} µs")
    print(f"   Median: {open_res['median_us']:.2f} µs")
    print(f"   p95:    {open_res['p95_us']:.2f} µs")
    print(f"   p99:    {open_res['p99_us']:.2f} µs")
    print(f"   Throughput: {open_res['ops_per_sec']:,.0f} ops/sec")

    print("\n3. Measuring Concurrent Lock Contention (100 coroutines, 20,000 total calls)...")
    conc_res = await benchmark_concurrent_contention(100, 200)
    print(f"   Mean:   {conc_res['mean_us']:.2f} µs")
    print(f"   Median: {conc_res['median_us']:.2f} µs")
    print(f"   p95:    {conc_res['p95_us']:.2f} µs")
    print(f"   p99:    {conc_res['p99_us']:.2f} µs")
    print(f"   Throughput: {conc_res['ops_per_sec']:,.0f} ops/sec")

    print("\n" + "=" * 60)
    print("BENCHMARK COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
