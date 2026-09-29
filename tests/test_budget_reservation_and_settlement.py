from uuid import uuid4

import pytest
from gateway.src.budgets.manager import BudgetLimits, InMemoryBudgetBackend


@pytest.mark.asyncio
async def test_budget_reservation_allowed():
    backend = InMemoryBudgetBackend()
    t_id = uuid4()
    p_id = uuid4()

    limits = BudgetLimits(
        tenant_monthly_limit=100_000,
        project_monthly_limit=50_000,
    )
    res = await backend.reserve(
        tenant_id=t_id,
        project_id=p_id,
        estimated_cost=25_000,
        limits=limits,
    )
    assert res.allowed is True
    assert res.reservation_id is not None


@pytest.mark.asyncio
async def test_budget_reservation_rejected_tenant_exceeded():
    backend = InMemoryBudgetBackend()
    t_id = uuid4()
    p_id = uuid4()

    limits = BudgetLimits(
        tenant_monthly_limit=10_000,
        project_monthly_limit=50_000,
    )
    # Request needs 15,000, but Tenant monthly budget is 10,000
    res = await backend.reserve(
        tenant_id=t_id,
        project_id=p_id,
        estimated_cost=15_000,
        limits=limits,
    )
    assert res.allowed is False
    assert res.rejection_reason == "budget_exceeded"
    assert "tenant" in res.scope


@pytest.mark.asyncio
async def test_budget_reservation_rejected_project_exceeded():
    backend = InMemoryBudgetBackend()
    t_id = uuid4()
    p_id = uuid4()

    limits = BudgetLimits(
        tenant_monthly_limit=100_000,
        project_monthly_limit=5_000,
    )
    # Request needs 10,000, Tenant has 100k, but Project only has 5k
    res = await backend.reserve(
        tenant_id=t_id,
        project_id=p_id,
        estimated_cost=10_000,
        limits=limits,
    )
    assert res.allowed is False
    assert res.rejection_reason == "budget_exceeded"
    assert "project" in res.scope


@pytest.mark.asyncio
async def test_budget_release_restores_capacity():
    backend = InMemoryBudgetBackend()
    t_id = uuid4()
    p_id = uuid4()

    limits = BudgetLimits(tenant_monthly_limit=10_000)

    # 1. Reserve 8,000
    res1 = await backend.reserve(
        tenant_id=t_id,
        project_id=p_id,
        estimated_cost=8_000,
        limits=limits,
    )
    assert res1.allowed is True

    # 2. Try to reserve another 5,000 (8k + 5k > 10k) -> rejected
    res2 = await backend.reserve(
        tenant_id=t_id,
        project_id=p_id,
        estimated_cost=5_000,
        limits=limits,
    )
    assert res2.allowed is False

    # 3. Release first reservation
    released = await backend.release(res1.reservation_id)
    assert released is True

    # 4. Now 5,000 reservation succeeds!
    res3 = await backend.reserve(
        tenant_id=t_id,
        project_id=p_id,
        estimated_cost=5_000,
        limits=limits,
    )
    assert res3.allowed is True


@pytest.mark.asyncio
async def test_budget_reservation_lease_expiration():
    simulated_time = 1000.0

    def get_time():
        return simulated_time

    backend = InMemoryBudgetBackend(now_func=get_time)
    t_id = uuid4()
    p_id = uuid4()

    limits = BudgetLimits(tenant_monthly_limit=10_000)

    # Reserve with 60s TTL
    res = await backend.reserve(
        tenant_id=t_id,
        project_id=p_id,
        estimated_cost=9_000,
        limits=limits,
        ttl_seconds=60,
        now=simulated_time,
    )
    assert res.allowed is True

    # Another 5k rejected immediately
    res_fail = await backend.reserve(
        tenant_id=t_id,
        project_id=p_id,
        estimated_cost=5_000,
        limits=limits,
        now=simulated_time,
    )
    assert res_fail.allowed is False

    # Advance time by 61 seconds (past lease TTL)
    simulated_time += 61.0

    # The expired reservation should automatically be cleared on next check!
    res_ok = await backend.reserve(
        tenant_id=t_id,
        project_id=p_id,
        estimated_cost=5_000,
        limits=limits,
        now=simulated_time,
    )
    assert res_ok.allowed is True
