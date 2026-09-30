import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from gateway.src.budgets.manager import (
    BudgetLimits,
    InMemoryBudgetBackend,
    budget_manager,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import UsageDailyRollup, UsageEvent
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.persistence import persist_usage_event


@pytest.mark.asyncio
async def test_budget_reservation_ttl_eviction_prevents_leakage():
    """
    Simulates a gateway crash immediately after creating a budget reservation:
    The provider is never called, and settle/release is never invoked.
    Verifies that the reservation expires via TTL and restores tenant balance capacity.
    """
    backend = InMemoryBudgetBackend()

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    limits = BudgetLimits(tenant_daily_limit=5000, tenant_monthly_limit=50000)

    # 1. Create reservation for 4,000 micro-cents with 1 second TTL
    res = await backend.reserve(
        tenant_id=tenant_id,
        project_id=project_id,
        estimated_cost=4000,
        limits=limits,
        ttl_seconds=1,
    )
    assert res.allowed is True

    # 2. Immediate second reservation for 2,000 fails (4000 + 2000 > 5000 limit)
    res_fail = await backend.reserve(
        tenant_id=tenant_id,
        project_id=project_id,
        estimated_cost=2000,
        limits=limits,
        ttl_seconds=1,
    )
    assert res_fail.allowed is False

    # 3. Simulate process crash: no settlement occurs. Wait 1.1s for reservation TTL expiration
    await asyncio.sleep(1.1)

    # 4. After TTL expiration, the orphaned reservation has vanished.
    # The tenant can now reserve 4,000 micro-cents again without budget leakage.
    res_recovered = await backend.reserve(
        tenant_id=tenant_id,
        project_id=project_id,
        estimated_cost=4000,
        limits=limits,
        ttl_seconds=1,
    )
    assert res_recovered.allowed is True


@pytest.mark.asyncio
async def test_ledger_reconciliation_after_redis_state_loss(db_session: AsyncSession):
    """
    Verifies that after an unrecoverable Redis crash or flush, the ground-truth
    financial balances can be accurately reconciled from PostgreSQL usage rollups.
    """
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()

    # Insert 3 confirmed usage events
    events = [
        UsageEventPayload(
            event_id=uuid.uuid4(),
            event_version="1.0",
            request_id=f"req_rec_{i}",
            reservation_id=f"res_rec_{i}",
            tenant_id=tenant_id,
            project_id=project_id,
            api_key_id=uuid.uuid4(),
            provider="openai",
            model="gpt-4o",
            stream=False,
            status="success",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost=3000,
            actual_cost=2000 + (i * 500), # 2000, 2500, 3000 -> Total: 7500
            latency_ms=100.0,
            attempt_count=1,
            fallback_used=False,
            created_at=datetime.now(timezone.utc),
        )
        for i in range(3)
    ]

    for ev in events:
        await persist_usage_event(db_session, ev)
    await db_session.commit()

    # Reconcile total spend from PostgreSQL
    today_date = datetime.now(timezone.utc).date()
    reconciliation_stmt = select(func.sum(UsageDailyRollup.actual_cost)).where(
        UsageDailyRollup.tenant_id == tenant_id,
        UsageDailyRollup.date == today_date,
    )
    reconciled_total = (await db_session.execute(reconciliation_stmt)).scalar()
    assert reconciled_total == 7500, f"Expected 7500 micro-cents, got {reconciled_total}"

    # Verify matching raw event sum
    raw_sum_stmt = select(func.sum(UsageEvent.actual_cost)).where(
        UsageEvent.tenant_id == tenant_id
    )
    raw_total = (await db_session.execute(raw_sum_stmt)).scalar()
    assert raw_total == 7500


@pytest.mark.asyncio
async def test_budget_settlement_recovers_unused_reservation_difference():
    """
    Verifies that when actual cost is lower than estimated reservation cost,
    the unused difference is returned immediately to the tenant's spending balance.
    """
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    limits = BudgetLimits(tenant_daily_limit=5000, tenant_monthly_limit=50000)

    # Reserve 4,000 micro-cents
    res = await budget_manager.reserve(
        tenant_id=tenant_id,
        project_id=project_id,
        estimated_cost=4000,
        limits=limits,
    )
    assert res.allowed is True

    # Settle with actual cost 1,500 micro-cents (releasing 2,500 micro-cents)
    settle_res = await budget_manager.settle(
        reservation_id=res.reservation_id,
        actual_cost=1500,
    )
    assert settle_res.success is True
    assert settle_res.refund == 2500

    # Tenant should now be able to reserve 3,000 micro-cents (1500 spent + 3000 = 4500 <= 5000)
    res_subsequent = await budget_manager.reserve(
        tenant_id=tenant_id,
        project_id=project_id,
        estimated_cost=3000,
        limits=limits,
    )
    assert res_subsequent.allowed is True
