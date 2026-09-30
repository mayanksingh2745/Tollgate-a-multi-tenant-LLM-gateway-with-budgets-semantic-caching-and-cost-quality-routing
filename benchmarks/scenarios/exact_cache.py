"""
Exact Cache Performance, Hit/Miss Scaling & Correctness Matrix Benchmark (Phase 13, Sections 8 & 9).

Measures:
1. Hit latency reduction vs Direct Upstream
2. Mixed Workload Scaling (10%, 25%, 50%, 75%, 90% repeated requests)
3. Correctness & Multi-Tenant Isolation Suite:
   - Same query, same tenant -> HIT
   - Same query, temperature changed -> MISS
   - Same query, model changed -> MISS
   - Same query, system instructions changed -> MISS
   - Same query, tool schemas added -> MISS
   - Same query, different tenant -> MISS (Strict isolation, zero cross-tenant leakage)
   - Same query, same tenant, different project -> MISS (Project isolation)
"""

import time
from typing import List
from uuid import uuid4

from gateway.src.auth.context import AuthenticatedContext
from gateway.src.cache.service import ExactResponseCache, InMemoryCacheBackend
from gateway.src.schemas.chat import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    UsageInfo,
)

from benchmarks.scenarios.base import BenchmarkResult, compute_percentiles


def _make_dummy_response(content: str = "Cached response content") -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id=f"resp-{uuid4()}",
        object="chat.completion",
        created=int(time.time()),
        model="gpt-4o",
        choices=[
            ChatChoice(
                index=0,
                message=ChatChoiceMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=UsageInfo(prompt_tokens=20, completion_tokens=10, total_tokens=30),
    )


async def run_exact_cache_benchmark(
    request_count: int = 500,
    hit_ratios: List[float] = None,
) -> BenchmarkResult:
    """Executes exact cache performance evaluation and correctness verification."""
    if hit_ratios is None:
        hit_ratios = [0.1, 0.25, 0.5, 0.75, 0.9]
    backend = InMemoryCacheBackend()
    cache = ExactResponseCache(backend=backend)

    tenant_a = uuid4()
    project_a = uuid4()
    ctx_a = AuthenticatedContext(
        api_key_id=uuid4(),
        user_id=None,
        project_id=project_a,
        tenant_id=tenant_a,
        role="admin",
    )

    base_req = ChatCompletionRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="system", content="You are a helpful assistant"),
            ChatMessage(role="user", content="Explain quantum computing in one sentence"),
        ],
        temperature=0.7,
    )

    # 1. Warm cache with baseline response
    dummy_resp = _make_dummy_response()
    await cache.set(
        request=base_req,
        response=dummy_resp,
        tenant_id=ctx_a.tenant_id,
        project_id=ctx_a.project_id,
        provider="openai",
    )

    # 2. Performance: 100% Cache Hit Benchmark
    hit_latencies_ms = []
    for _ in range(request_count):
        t0 = time.perf_counter()
        cached = await cache.get(
            request=base_req,
            tenant_id=ctx_a.tenant_id,
            project_id=ctx_a.project_id,
            provider="openai",
        )
        hit_latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        assert cached is not None

    hit_stats = compute_percentiles(hit_latencies_ms)

    # 3. Mixed Workload Simulation
    mixed_results = {}
    for ratio in hit_ratios:
        latencies = []
        hits = 0
        misses = 0

        for i in range(200):
            # If within ratio, send base_req (HIT), otherwise send unique query (MISS)
            if (i % 100) < (ratio * 100):
                req = base_req
            else:
                req = ChatCompletionRequest(
                    model="gpt-4o",
                    messages=[ChatMessage(role="user", content=f"Unique query {uuid4()}")],
                )

            t0 = time.perf_counter()
            res = await cache.get(
                request=req,
                tenant_id=ctx_a.tenant_id,
                project_id=ctx_a.project_id,
                provider="openai",
            )
            dur = (time.perf_counter() - t0) * 1000.0
            latencies.append(dur)

            if res is not None:
                hits += 1
            else:
                misses += 1
                # If miss, populate cache as gateway would
                await cache.set(
                    request=req,
                    response=_make_dummy_response(),
                    tenant_id=ctx_a.tenant_id,
                    project_id=ctx_a.project_id,
                    provider="openai",
                )

        stats = compute_percentiles(latencies)
        actual_hit_rate = round(hits / (hits + misses), 3)
        mixed_results[f"{int(ratio*100)}pct_hits"] = {
            "target_hit_ratio": ratio,
            "actual_hit_rate": actual_hit_rate,
            "p50_ms": stats["p50"],
            "p95_ms": stats["p95"],
            "p99_ms": stats["p99"],
            "provider_call_reduction_pct": round(actual_hit_rate * 100, 1),
            "estimated_cost_reduction_pct": round(actual_hit_rate * 100, 1),
        }

    # 4. Correctness & Isolation Test Suite
    correctness_suite = {}

    # Case 1: Identical request -> MUST HIT
    res = await cache.get(request=base_req, tenant_id=ctx_a.tenant_id, project_id=ctx_a.project_id, provider="openai")
    correctness_suite["identical_request"] = {"expected": "hit", "actual": "hit" if res else "miss", "passed": res is not None}

    # Case 2: Temperature change (0.7 -> 0.2) -> MUST MISS
    req_temp = base_req.model_copy(update={"temperature": 0.2})
    res = await cache.get(request=req_temp, tenant_id=ctx_a.tenant_id, project_id=ctx_a.project_id, provider="openai")
    correctness_suite["temperature_change"] = {"expected": "miss", "actual": "hit" if res else "miss", "passed": res is None}

    # Case 3: Model change (gpt-4o -> gpt-4o-mini) -> MUST MISS
    req_model = base_req.model_copy(update={"model": "gpt-4o-mini"})
    res = await cache.get(request=req_model, tenant_id=ctx_a.tenant_id, project_id=ctx_a.project_id, provider="openai")
    correctness_suite["model_change"] = {"expected": "miss", "actual": "hit" if res else "miss", "passed": res is None}

    # Case 4: System prompt change -> MUST MISS
    req_sys = ChatCompletionRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="system", content="You are a pirate"),
            ChatMessage(role="user", content="Explain quantum computing in one sentence"),
        ],
        temperature=0.7,
    )
    res = await cache.get(request=req_sys, tenant_id=ctx_a.tenant_id, project_id=ctx_a.project_id, provider="openai")
    correctness_suite["system_prompt_change"] = {"expected": "miss", "actual": "hit" if res else "miss", "passed": res is None}

    # Case 5: Tools difference -> MUST MISS
    req_tools = base_req.model_copy(update={"tools": [{"type": "function", "function": {"name": "search"}}]})
    res = await cache.get(request=req_tools, tenant_id=ctx_a.tenant_id, project_id=ctx_a.project_id, provider="openai")
    correctness_suite["tools_difference"] = {"expected": "miss", "actual": "hit" if res else "miss", "passed": res is None}

    # Case 6: Cross-Tenant Isolation (Tenant B sends identical query) -> MUST MISS
    ctx_b = AuthenticatedContext(
        api_key_id=uuid4(),
        user_id=None,
        project_id=uuid4(),
        tenant_id=uuid4(), # Different tenant!
        role="admin",
    )
    res = await cache.get(request=base_req, tenant_id=ctx_b.tenant_id, project_id=ctx_b.project_id, provider="openai")
    correctness_suite["cross_tenant_isolation"] = {"expected": "miss", "actual": "hit" if res else "miss", "passed": res is None}

    # Case 7: Cross-Project Isolation (Tenant A, Project 2) -> MUST MISS
    ctx_a_proj2 = AuthenticatedContext(
        api_key_id=uuid4(),
        user_id=None,
        project_id=uuid4(), # Different project in same tenant!
        tenant_id=tenant_a,
        role="admin",
    )
    res = await cache.get(request=base_req, tenant_id=ctx_a_proj2.tenant_id, project_id=ctx_a_proj2.project_id, provider="openai")
    correctness_suite["cross_project_isolation"] = {"expected": "miss", "actual": "hit" if res else "miss", "passed": res is None}

    all_correctness_passed = all(v["passed"] for v in correctness_suite.values())

    return BenchmarkResult(
        benchmark="cache_evaluation",
        scenario="exact_cache_and_correctness",
        requests_total=request_count,
        requests_successful=request_count,
        requests_failed=0,
        throughput_rps=round(request_count / (sum(hit_latencies_ms) / 1000.0), 2),
        latency_ms=hit_stats,
        details={
            "hit_latency_p50_us": round(hit_stats["p50"] * 1000.0, 2),
            "hit_latency_p99_us": round(hit_stats["p99"] * 1000.0, 2),
            "mixed_workload_analysis": mixed_results,
            "correctness_suite": correctness_suite,
            "all_correctness_passed": all_correctness_passed,
            "cross_tenant_leakage_detected": not correctness_suite["cross_tenant_isolation"]["passed"],
        },
    )
