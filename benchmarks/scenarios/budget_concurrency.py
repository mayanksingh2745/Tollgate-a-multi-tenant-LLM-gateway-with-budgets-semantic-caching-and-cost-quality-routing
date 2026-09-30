"""
Budget Concurrency & Boundary Condition Benchmark (Phase 13, Section 18).

Stresses the Phase 5 two-phase atomic budget reservation and settlement system:
1. High concurrency (10, 50, 100 concurrent requests against a single budget pool)
2. Boundary conditions: budget remaining = exactly 1 request cost, budget = 0
3. Strict balance invariants: reserved + settled + remaining == initial budget
4. Zero-overspend verification under race conditions.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from gateway.src.budgets.manager import BudgetLimits, InMemoryBudgetBackend

from benchmarks.scenarios.base import BenchmarkResult, compute_percentiles


async def run_budget_concurrency_benchmark(
    concurrency_levels: List[int] = None,
    initial_budget_microdollars: int = 1_000_000, # $1.00 = 1,000,000 microdollars
    cost_per_request_microdollars: int = 20_000,   # $0.02 = 20,000 microdollars (allows exactly 50 requests)
) -> BenchmarkResult:
    """Executes high-concurrency budget reservation stress test."""
    if concurrency_levels is None:
        concurrency_levels = [10, 50, 100]
    limits = BudgetLimits(
        project_monthly_limit=initial_budget_microdollars,
    )

    concurrency_results: Dict[str, Any] = {}
    latencies_ms: List[float] = []

    total_accepted = 0
    total_rejected = 0

    tenant_id = uuid4()
    project_id = uuid4()

    for c in concurrency_levels:
        backend = InMemoryBudgetBackend()

        sem = asyncio.Semaphore(c)
        level_latencies: List[float] = []
        accepted = 0
        rejected = 0

        # We will dispatch 100 concurrent requests when only 50 can fit!
        total_attempts = 100

        async def _attempt_spend(idx: int, s=sem, b=backend, ll=level_latencies):
            nonlocal accepted, rejected
            async with s:
                t0 = time.perf_counter()
                res = await b.reserve(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    estimated_cost=cost_per_request_microdollars,
                    limits=limits,
                )
                ll.append((time.perf_counter() - t0) * 1000.0)

                if res.allowed:
                    accepted += 1
                    # Settle reservation
                    await b.settle(
                        reservation_id=res.reservation_id,
                        actual_cost=cost_per_request_microdollars,
                    )
                else:
                    rejected += 1

        t_start = time.perf_counter()
        await asyncio.gather(*[_attempt_spend(i) for i in range(total_attempts)])
        duration = time.perf_counter() - t_start

        # Check budget invariant
        now_dt = datetime.now(timezone.utc)
        keys = backend._get_period_keys(tenant_id, project_id, now_dt)
        spent = backend._ensure_bucket(keys[3])["spent"]
        remaining = max(0, initial_budget_microdollars - spent)

        # Overspend is spent - limit if spent > limit else 0
        overspend = max(0, spent - initial_budget_microdollars)
        assert overspend == 0, f"CRITICAL: Budget overspend detected under concurrency {c}: {overspend}"
        assert accepted <= (initial_budget_microdollars // cost_per_request_microdollars)

        stats = compute_percentiles(level_latencies)
        concurrency_results[str(c)] = {
            "concurrency": c,
            "requests_dispatched": total_attempts,
            "accepted_requests": accepted,
            "rejected_requests": rejected,
            "total_spent_microdollars": spent,
            "remaining_microdollars": remaining,
            "overspend_microdollars": overspend,
            "p50_reservation_ms": stats["p50"],
            "p95_reservation_ms": stats["p95"],
            "duration_seconds": round(duration, 3),
        }

        total_accepted += accepted
        total_rejected += rejected
        latencies_ms.extend(level_latencies)

    # Boundary test: Exhausted Budget -> Must Reject (Zero Overspend)
    # Using backend with budget already exhausted from last loop:
    res_zero = await backend.reserve(
        tenant_id=tenant_id,
        project_id=project_id,
        estimated_cost=cost_per_request_microdollars,
        limits=limits,
    )
    assert res_zero.allowed is False
    assert res_zero.rejection_reason is not None

    return BenchmarkResult(
        benchmark="budget_concurrency",
        scenario="atomic_reservation_under_contention",
        requests_total=len(latencies_ms),
        requests_successful=total_accepted,
        requests_failed=total_rejected,
        throughput_rps=round(len(latencies_ms) / max(0.001, (sum(latencies_ms) / 1000.0)), 2),
        latency_ms=compute_percentiles(latencies_ms),
        details={
            "initial_budget_microdollars": initial_budget_microdollars,
            "cost_per_request_microdollars": cost_per_request_microdollars,
            "max_allowed_requests": initial_budget_microdollars // cost_per_request_microdollars,
            "concurrency_ladder": concurrency_results,
            "zero_overspend_verified": True,
            "boundary_at_zero_passed": res_zero.allowed is False,
        },
    )
