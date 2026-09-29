import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import (
    Project,
    Tenant,
    UsageDailyRollup,
    UsageEvent,
    UsageMonthlyRollup,
)
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.persistence import persist_usage_event


@pytest.mark.asyncio
async def test_persist_usage_event_and_rollups(db_session: AsyncSession):
    # Setup Tenant & Project
    t_id = uuid.uuid4()
    p_id = uuid.uuid4()
    tenant = Tenant(id=t_id, name="Usage Test Tenant", slug="usage-test")
    project = Project(id=p_id, tenant_id=t_id, name="Usage Test Project", slug="usage-proj")
    db_session.add_all([tenant, project])
    await db_session.commit()

    now = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
    event1 = UsageEventPayload(
        event_id=uuid.uuid4(),
        event_version=1,
        request_id="req_persist_1",
        reservation_id="res_persist_1",
        timestamp=now,
        tenant_id=t_id,
        project_id=p_id,
        provider="openai",
        model="gpt-4o",
        stream=False,
        status="success",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        estimated_cost=3000,
        actual_cost=2500,
        latency_ms=210.5,
        attempt_count=1,
        fallback_used=False,
    )

    # Persist event
    res1 = await persist_usage_event(db_session, event1)
    await db_session.commit()
    assert res1 is True

    # 1. Verify usage_events record
    events = (
        (await db_session.execute(select(UsageEvent).where(UsageEvent.tenant_id == t_id)))
        .scalars()
        .all()
    )
    assert len(events) == 1
    ev = events[0]
    assert ev.event_id == event1.event_id
    assert ev.request_id == "req_persist_1"
    assert ev.actual_cost == 2500
    assert ev.estimated_cost == 3000
    assert ev.total_tokens == 150
    assert ev.status == "success"

    # 2. Verify Daily Rollup
    daily_rows = (
        (
            await db_session.execute(
                select(UsageDailyRollup).where(UsageDailyRollup.tenant_id == t_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(daily_rows) == 1
    daily = daily_rows[0]
    assert daily.date == "2026-09-30"
    assert daily.request_count == 1
    assert daily.success_count == 1
    assert daily.failure_count == 0
    assert daily.input_tokens == 100
    assert daily.output_tokens == 50
    assert daily.total_tokens == 150
    assert daily.actual_cost == 2500

    # 3. Verify Monthly Rollup
    monthly_rows = (
        (
            await db_session.execute(
                select(UsageMonthlyRollup).where(UsageMonthlyRollup.tenant_id == t_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(monthly_rows) == 1
    monthly = monthly_rows[0]
    assert monthly.month == "2026-09"
    assert monthly.request_count == 1
    assert monthly.actual_cost == 2500


@pytest.mark.asyncio
async def test_persist_multiple_events_and_rollups(db_session: AsyncSession):
    t_id = uuid.uuid4()
    p_id = uuid.uuid4()
    tenant = Tenant(id=t_id, name="Rollup Tenant", slug="rollup-tenant")
    project = Project(id=p_id, tenant_id=t_id, name="Rollup Project", slug="rollup-proj")
    db_session.add_all([tenant, project])
    await db_session.commit()

    now = datetime(2026, 9, 30, 14, 0, 0, tzinfo=timezone.utc)
    event1 = UsageEventPayload(
        event_id=uuid.uuid4(),
        request_id="req_multi_1",
        timestamp=now,
        tenant_id=t_id,
        project_id=p_id,
        provider="openai",
        model="gpt-4o",
        status="success",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        estimated_cost=3000,
        actual_cost=2000,
    )
    event2 = UsageEventPayload(
        event_id=uuid.uuid4(),
        request_id="req_multi_2",
        timestamp=now,
        tenant_id=t_id,
        project_id=p_id,
        provider="openai",
        model="gpt-4o",
        status="provider_failure",
        input_tokens=50,
        output_tokens=0,
        total_tokens=50,
        estimated_cost=1500,
        actual_cost=500,
    )

    await persist_usage_event(db_session, event1)
    await persist_usage_event(db_session, event2)
    await db_session.commit()

    daily = (
        await db_session.execute(select(UsageDailyRollup).where(UsageDailyRollup.tenant_id == t_id))
    ).scalar_one()
    assert daily.request_count == 2
    assert daily.success_count == 1
    assert daily.failure_count == 1
    assert daily.total_tokens == 200
    assert daily.actual_cost == 2500
    assert daily.estimated_cost == 4500


@pytest.mark.asyncio
async def test_idempotent_duplicate_events_prevent_double_counting(db_session: AsyncSession):
    t_id = uuid.uuid4()
    p_id = uuid.uuid4()
    tenant = Tenant(id=t_id, name="Idempotency Tenant", slug="idempotent-tenant")
    project = Project(id=p_id, tenant_id=t_id, name="Idempotency Project", slug="idempotent-proj")
    db_session.add_all([tenant, project])
    await db_session.commit()

    event_id = uuid.uuid4()
    event = UsageEventPayload(
        event_id=event_id,
        request_id="req_idempotent",
        timestamp=datetime(2026, 9, 30, 10, 0, 0, tzinfo=timezone.utc),
        tenant_id=t_id,
        project_id=p_id,
        provider="openai",
        model="gpt-4o",
        status="success",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        estimated_cost=3000,
        actual_cost=2500,
    )

    # First delivery
    res1 = await persist_usage_event(db_session, event)
    await db_session.commit()
    assert res1 is True

    # Duplicate delivery of exact same event
    res2 = await persist_usage_event(db_session, event)
    await db_session.commit()
    assert res2 is False  # Safely ignored!

    # Verify usage_events has only 1 row
    events = (
        (await db_session.execute(select(UsageEvent).where(UsageEvent.tenant_id == t_id)))
        .scalars()
        .all()
    )
    assert len(events) == 1

    # Verify rollups were NOT double counted!
    daily = (
        await db_session.execute(select(UsageDailyRollup).where(UsageDailyRollup.tenant_id == t_id))
    ).scalar_one()
    assert daily.request_count == 1
    assert daily.total_tokens == 150
    assert daily.actual_cost == 2500
