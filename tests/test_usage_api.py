import uuid
from datetime import datetime, timezone
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.persistence import persist_usage_event


async def create_tenant_and_key(async_client: AsyncClient, slug: str):
    t_res = await async_client.post("/api/v1/tenants", json={"name": slug, "slug": slug})
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": f"{slug}-proj", "slug": f"{slug}-proj"},
    )
    project_id = p_res.json()["id"]

    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": f"{slug}-key"}
    )
    key_data = k_res.json()
    return {
        "tenant_id": UUID(tenant_id),
        "project_id": UUID(project_id),
        "headers": {"Authorization": f"Bearer {key_data['key']}"},
    }


@pytest.mark.asyncio
async def test_usage_api_tenant_isolation(async_client: AsyncClient, db_session: AsyncSession):
    # Setup Tenant A and Tenant B
    a = await create_tenant_and_key(async_client, "tenant-a")
    b = await create_tenant_and_key(async_client, "tenant-b")

    now = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
    ev_a = UsageEventPayload(
        event_id=uuid.uuid4(),
        request_id="req_a",
        timestamp=now,
        tenant_id=a["tenant_id"],
        project_id=a["project_id"],
        provider="openai",
        model="gpt-4o",
        status="success",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        estimated_cost=2000,
        actual_cost=1500,
    )
    ev_b = UsageEventPayload(
        event_id=uuid.uuid4(),
        request_id="req_b",
        timestamp=now,
        tenant_id=b["tenant_id"],
        project_id=b["project_id"],
        provider="anthropic",
        model="claude-3-opus",
        status="success",
        input_tokens=200,
        output_tokens=100,
        total_tokens=300,
        estimated_cost=5000,
        actual_cost=4000,
    )

    await persist_usage_event(db_session, ev_a)
    await persist_usage_event(db_session, ev_b)
    await db_session.commit()

    # 1. Tenant A queries /api/v1/usage
    res_a = await async_client.get("/api/v1/usage", headers=a["headers"])
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert len(data_a["items"]) == 1
    assert data_a["items"][0]["request_id"] == "req_a"
    assert data_a["items"][0]["tenant_id"] == str(a["tenant_id"])

    # 2. Tenant A tries to explicitly query Tenant B's data
    res_cross = await async_client.get(
        f"/api/v1/usage?tenant_id={b['tenant_id']}", headers=a["headers"]
    )
    assert res_cross.status_code == 403
    assert "Cannot query usage for a different tenant" in res_cross.json()["detail"]


@pytest.mark.asyncio
async def test_usage_api_project_scoping(async_client: AsyncClient, db_session: AsyncSession):
    a = await create_tenant_and_key(async_client, "proj-scope-tenant")

    # Create second project in same tenant
    p2_res = await async_client.post(
        f"/api/v1/tenants/{a['tenant_id']}/projects", json={"name": "proj-2", "slug": "proj-2"}
    )
    proj2_id = UUID(p2_res.json()["id"])

    # Query with key scoped to project 1 trying to access project 2
    res_cross_proj = await async_client.get(
        f"/api/v1/usage?project_id={proj2_id}", headers=a["headers"]
    )
    assert res_cross_proj.status_code == 403
    assert "scoped to a different project" in res_cross_proj.json()["detail"]


@pytest.mark.asyncio
async def test_usage_api_filters_and_cursor_pagination(
    async_client: AsyncClient, db_session: AsyncSession
):
    t = await create_tenant_and_key(async_client, "filter-tenant")

    # Insert 5 events
    base_time = datetime(2026, 9, 30, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        event = UsageEventPayload(
            event_id=uuid.uuid4(),
            request_id=f"req_page_{i}",
            timestamp=base_time,
            tenant_id=t["tenant_id"],
            project_id=t["project_id"],
            provider="openai",
            model="gpt-4o" if i % 2 == 0 else "gpt-3.5-turbo",
            status="success",
            input_tokens=10 * (i + 1),
            output_tokens=5 * (i + 1),
            total_tokens=15 * (i + 1),
            estimated_cost=100 * (i + 1),
            actual_cost=80 * (i + 1),
        )
        await persist_usage_event(db_session, event)
    await db_session.commit()

    # Filter by model
    res_filter = await async_client.get("/api/v1/usage?model=gpt-3.5-turbo", headers=t["headers"])
    assert res_filter.status_code == 200
    assert len(res_filter.json()["items"]) == 2

    # Test limit=2 pagination
    res_p1 = await async_client.get("/api/v1/usage?limit=2", headers=t["headers"])
    assert res_p1.status_code == 200
    p1_data = res_p1.json()
    assert len(p1_data["items"]) == 2
    assert p1_data["has_more"] is True
    assert p1_data["next_cursor"] is not None

    # Fetch page 2 using cursor
    res_p2 = await async_client.get(
        f"/api/v1/usage?limit=2&cursor={p1_data['next_cursor']}", headers=t["headers"]
    )
    assert res_p2.status_code == 200
    p2_data = res_p2.json()
    assert len(p2_data["items"]) == 2

    # Ensure items in page 1 and page 2 are disjoint
    p1_ids = {item["id"] for item in p1_data["items"]}
    p2_ids = {item["id"] for item in p2_data["items"]}
    assert p1_ids.isdisjoint(p2_ids)


@pytest.mark.asyncio
async def test_usage_rollups_endpoints(async_client: AsyncClient, db_session: AsyncSession):
    t = await create_tenant_and_key(async_client, "rollups-endpoint-tenant")

    now = datetime(2026, 9, 30, 15, 0, 0, tzinfo=timezone.utc)
    ev = UsageEventPayload(
        event_id=uuid.uuid4(),
        request_id="req_rollup_ep",
        timestamp=now,
        tenant_id=t["tenant_id"],
        project_id=t["project_id"],
        provider="openai",
        model="gpt-4o",
        status="success",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        estimated_cost=2000,
        actual_cost=1800,
    )
    await persist_usage_event(db_session, ev)
    await db_session.commit()

    # Query daily rollups
    res_daily = await async_client.get("/api/v1/usage/rollups/daily", headers=t["headers"])
    assert res_daily.status_code == 200
    daily_list = res_daily.json()
    assert len(daily_list) == 1
    assert daily_list[0]["date"] == "2026-09-30"
    assert daily_list[0]["actual_cost"] == 1800

    # Query monthly rollups
    res_monthly = await async_client.get("/api/v1/usage/rollups/monthly", headers=t["headers"])
    assert res_monthly.status_code == 200
    monthly_list = res_monthly.json()
    assert len(monthly_list) == 1
    assert monthly_list[0]["month"] == "2026-09"
    assert monthly_list[0]["actual_cost"] == 1800
