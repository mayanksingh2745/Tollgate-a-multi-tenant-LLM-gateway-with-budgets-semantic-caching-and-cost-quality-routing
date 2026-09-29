import asyncio
import platform
import sys
import time
import uuid
from pathlib import Path

# Add core and apps to path
root_dir = Path(__file__).resolve().parents[1]
core_src = root_dir / "packages" / "core" / "src"
apps_dir = root_dir / "apps"

for p in [str(root_dir), str(apps_dir), str(core_src)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from gateway.src.cache.canonicalizer import Canonicalizer
from gateway.src.cache.service import ExactResponseCache, InMemoryCacheBackend
from gateway.src.schemas.chat import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    UsageInfo,
)


async def run_benchmark(num_requests: int = 1000):
    print("==========================================================")
    print("       TOLLGATE PHASE 7: EXACT RESPONSE CACHE BENCHMARK   ")
    print("==========================================================")
    print(f"OS: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python: {platform.python_version()}")
    print(f"Total iterations: {num_requests}")

    backend = InMemoryCacheBackend()
    cache = ExactResponseCache(backend=backend)

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    provider = "openai"

    request = ChatCompletionRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="system", content="You are a helpful customer support assistant."),
            ChatMessage(role="user", content="How do I reset my account password?"),
        ],
        temperature=0.0,
        max_tokens=250,
    )

    response = ChatCompletionResponse(
        id="chatcmpl-bench123",
        created=int(time.time()),
        model="gpt-4o",
        choices=[
            ChatChoice(
                index=0,
                message=ChatChoiceMessage(
                    role="assistant",
                    content="To reset your password, navigate to Settings > Security > Change Password.",
                ),
                finish_reason="stop",
            )
        ],
        usage=UsageInfo(prompt_tokens=28, completion_tokens=18, total_tokens=46),
    )

    # 1. Benchmark Canonicalization & Hash Generation
    t0_canon = time.perf_counter()
    for _ in range(num_requests):
        _ = Canonicalizer.compute_hash(request, tenant_id, project_id, provider)
    t_canon_total = (time.perf_counter() - t0_canon) * 1000.0
    avg_canon = t_canon_total / num_requests

    print("\n--- 1. Canonicalization & Key Hashing (SHA-256) ---")
    print(f"Total time: {t_canon_total:.2f} ms")
    print(f"Average latency: {avg_canon:.4f} ms/req")
    print(f"Throughput: {num_requests / (t_canon_total / 1000.0):.0f} ops/sec")

    # 2. Benchmark Cache Miss (Cold Lookup)
    t0_miss = time.perf_counter()
    for _ in range(num_requests):
        miss_res = await cache.get(request, tenant_id, project_id, provider)
        assert miss_res is None
    t_miss_total = (time.perf_counter() - t0_miss) * 1000.0
    avg_miss = t_miss_total / num_requests

    print("\n--- 2. Cache Lookup MISS (Overhead on Cold Path) ---")
    print(f"Total time: {t_miss_total:.2f} ms")
    print(f"Average lookup latency: {avg_miss:.4f} ms/lookup")
    print(f"Throughput: {num_requests / (t_miss_total / 1000.0):.0f} lookups/sec")

    # 3. Benchmark Cache Write
    write_latencies = []
    t0_write = time.perf_counter()
    for _ in range(num_requests):
        t_w = time.perf_counter()
        written = await cache.set(request, response, tenant_id, project_id, provider)
        write_latencies.append((time.perf_counter() - t_w) * 1000.0)
        assert written is True
    t_write_total = (time.perf_counter() - t0_write) * 1000.0
    avg_write = t_write_total / num_requests

    write_latencies.sort()
    w_p50 = write_latencies[int(len(write_latencies) * 0.50)]
    w_p95 = write_latencies[int(len(write_latencies) * 0.95)]
    w_p99 = write_latencies[int(len(write_latencies) * 0.99)]

    print("\n--- 3. Cache Storage Write Latency ---")
    print(f"Total write time: {t_write_total:.2f} ms")
    print(f"Average write latency: {avg_write:.4f} ms")
    print(f"Write P50: {w_p50:.4f} ms | P95: {w_p95:.4f} ms | P99: {w_p99:.4f} ms")

    # 4. Benchmark Cache Hit (Warm Lookup & Deserialization)
    hit_latencies = []
    t0_hit = time.perf_counter()
    for _ in range(num_requests):
        t_h = time.perf_counter()
        hit_res = await cache.get(request, tenant_id, project_id, provider)
        hit_latencies.append((time.perf_counter() - t_h) * 1000.0)
        assert hit_res is not None
    t_hit_total = (time.perf_counter() - t0_hit) * 1000.0
    avg_hit = t_hit_total / num_requests

    hit_latencies.sort()
    h_p50 = hit_latencies[int(len(hit_latencies) * 0.50)]
    h_p95 = hit_latencies[int(len(hit_latencies) * 0.95)]
    h_p99 = hit_latencies[int(len(hit_latencies) * 0.99)]

    print("\n--- 4. Cache Lookup HIT Latency ---")
    print(f"Total hit lookup time: {t_hit_total:.2f} ms")
    print(f"Average hit latency: {avg_hit:.4f} ms")
    print(f"Hit P50: {h_p50:.4f} ms | P95: {h_p95:.4f} ms | P99: {h_p99:.4f} ms")
    print(f"Hit Throughput: {num_requests / (t_hit_total / 1000.0):.0f} req/sec")

    # 5. Comparison: Simulated Provider Call vs Exact Cache Hit
    simulated_provider_latency_ms = 450.0  # typical fast LLM provider latency
    speedup = simulated_provider_latency_ms / max(0.001, avg_hit)
    saved_cost_pct = 100.0  # 100% provider cost avoided

    print("\n--- 5. Provider Call vs Cache Hit Comparison ---")
    print(f"Typical Provider Round-trip: ~{simulated_provider_latency_ms:.1f} ms")
    print(f"Tollgate Cache Hit Latency: ~{avg_hit:.3f} ms")
    print(f"Effective Latency Reduction: {speedup:.1f}x speedup")
    print(f"Provider Cost Incurred on Hit: $0.00 ({saved_cost_pct:.0f}% savings)")
    print("==========================================================\n")


if __name__ == "__main__":
    asyncio.run(run_benchmark(1000))
