import asyncio
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import List

root_dir = Path(__file__).resolve().parents[1]
core_src = root_dir / "packages" / "core" / "src"
apps_dir = root_dir / "apps"

for p in [str(root_dir), str(apps_dir), str(core_src)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from gateway.src.cache.semantic.backend import InMemorySemanticCacheBackend
from gateway.src.cache.semantic.embeddings import MockEmbeddingProvider
from gateway.src.cache.semantic.representation import SemanticRepresentation
from gateway.src.cache.semantic.service import SemanticResponseCache
from gateway.src.cache.service import ExactResponseCache, InMemoryCacheBackend
from gateway.src.schemas.chat import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    UsageInfo,
)


def percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_d = sorted(data)
    idx = int(len(sorted_d) * (p / 100.0))
    idx = min(idx, len(sorted_d) - 1)
    return sorted_d[idx]


async def run_benchmark(iterations: int = 1000) -> None:
    print("\n=======================================================")
    print(f"TOLLGATE SEMANTIC CACHE BENCHMARK ({iterations} iterations)")
    print("=======================================================\n")

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    provider_name = "openai"

    exact_backend = InMemoryCacheBackend()
    exact_cache = ExactResponseCache(backend=exact_backend)

    sem_backend = InMemorySemanticCacheBackend()
    embedding_provider = MockEmbeddingProvider()
    sem_cache = SemanticResponseCache(
        backend=sem_backend,
        embedding_provider=embedding_provider,
    )
    sem_cache.exact_cache = exact_cache

    req_base = ChatCompletionRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="How does TCP congestion control work?"),
        ],
        temperature=1.0,
    )

    req_similar = ChatCompletionRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(
                role="user",
                content="Can you explain the mechanism behind TCP congestion control?",
            ),
        ],
        temperature=1.0,
    )

    req_different = ChatCompletionRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="What is the capital of France?"),
        ],
        temperature=1.0,
    )

    sample_resp = ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
        created=int(time.time()),
        model="gpt-4o",
        choices=[
            ChatChoice(
                index=0,
                message=ChatChoiceMessage(
                    role="assistant",
                    content="TCP congestion control throttles transmission using AIMD.",
                ),
                finish_reason="stop",
            )
        ],
        usage=UsageInfo(prompt_tokens=25, completion_tokens=15, total_tokens=40),
    )

    # 1. Benchmark Embedding Generation
    embedding_latencies = []
    text_to_embed = SemanticRepresentation.build_text_to_embed(req_base)
    for _ in range(iterations):
        t0 = time.perf_counter()
        _ = await embedding_provider.embed(text_to_embed)
        embedding_latencies.append((time.perf_counter() - t0) * 1000.0)

    # 2. Benchmark Exact Cache Hit
    await exact_cache.set(req_base, sample_resp, tenant_id, project_id, provider_name)
    exact_hit_latencies = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        _ = await exact_cache.get(req_base, tenant_id, project_id, provider_name)
        exact_hit_latencies.append((time.perf_counter() - t0) * 1000.0)

    # 3. Benchmark Semantic Cache Write
    response_key = await exact_cache.build_cache_key(req_base, tenant_id, project_id, provider_name)
    sem_write_latencies = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        await sem_cache.set(
            request=req_base,
            response=sample_resp,
            response_cache_key=response_key,
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider_name,
        )
        sem_write_latencies.append((time.perf_counter() - t0) * 1000.0)

    # 4. Benchmark Semantic Cache Hit
    # Temporarily enable semantic cache in settings
    from gateway.src.config import settings

    orig_sem_enabled = settings.semantic_cache_enabled
    orig_threshold = settings.semantic_cache_threshold
    settings.semantic_cache_enabled = True
    settings.semantic_cache_threshold = 0.85

    sem_hit_latencies = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        _ = await sem_cache.get(
            request=req_similar,
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider_name,
        )
        sem_hit_latencies.append((time.perf_counter() - t0) * 1000.0)

    # 5. Benchmark Semantic Cache Miss (Different Topic)
    sem_miss_latencies = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        _ = await sem_cache.get(
            request=req_different,
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider_name,
        )
        sem_miss_latencies.append((time.perf_counter() - t0) * 1000.0)

    # Reset settings
    settings.semantic_cache_enabled = orig_sem_enabled
    settings.semantic_cache_threshold = orig_threshold

    # Print summary table
    benchmarks = [
        ("Embedding Generation", embedding_latencies),
        ("Exact Cache Hit (Redis L1)", exact_hit_latencies),
        ("Semantic Cache Hit (L2)", sem_hit_latencies),
        ("Semantic Cache Miss (L2)", sem_miss_latencies),
        ("Semantic Cache Write (L2)", sem_write_latencies),
    ]

    print(
        f"{'Operation':<30} | {'Avg (ms)':<10} | {'P50 (ms)':<10} | {'P95 (ms)':<10} | {'P99 (ms)':<10} | {'Throughput':<15}"
    )
    print("-" * 96)
    for name, latencies in benchmarks:
        avg_l = statistics.mean(latencies)
        p50 = percentile(latencies, 50)
        p95 = percentile(latencies, 95)
        p99 = percentile(latencies, 99)
        tput = f"~{int(1000.0 / avg_l):,} ops/s" if avg_l > 0 else "N/A"
        print(
            f"{name:<30} | {avg_l:<10.4f} | {p50:<10.4f} | {p95:<10.4f} | {p99:<10.4f} | {tput:<15}"
        )
    print("=" * 96 + "\n")


if __name__ == "__main__":
    asyncio.run(run_benchmark(1000))
