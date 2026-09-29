import asyncio
from uuid import uuid4

import pytest
from gateway.src.budgets.manager import BudgetLimits, InMemoryBudgetBackend


@pytest.mark.asyncio
async def test_concurrent_budget_reservations_atomic():
    """
    Mandatory Concurrency Test (Section 33):
    Budget = $1.00 (1,000,000 microdollars).
    100 concurrent tasks race simultaneously to reserve $0.10 (100,000 microdollars) each.
    Atomicity guarantee:
    Exactly 10 requests must be allowed.
    Exactly 90 requests must be rejected.
    Committed + reserved can never exceed 1,000,000 microdollars.
    """
    backend = InMemoryBudgetBackend()
    tenant_id = uuid4()
    project_id = uuid4()

    limits = BudgetLimits(
        tenant_monthly_limit=1_000_000,  # $1.00
    )

    async def attempt_reservation():
        return await backend.reserve(
            tenant_id=tenant_id,
            project_id=project_id,
            estimated_cost=100_000,  # $0.10
            limits=limits,
        )

    # Launch 100 concurrent tasks simultaneously
    tasks = [attempt_reservation() for _ in range(100)]
    results = await asyncio.gather(*tasks)

    allowed = [r for r in results if r.allowed]
    rejected = [r for r in results if not r.allowed]

    assert len(allowed) == 10, f"Expected exactly 10 allowed reservations, got {len(allowed)}"
    assert len(rejected) == 90, f"Expected exactly 90 rejected reservations, got {len(rejected)}"

    # Attempting 101st reservation must also fail
    final_attempt = await backend.reserve(
        tenant_id=tenant_id,
        project_id=project_id,
        estimated_cost=1,
        limits=limits,
    )
    assert final_attempt.allowed is False
