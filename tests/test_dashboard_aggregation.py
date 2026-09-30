"""Tests for Dashboard Metrics Aggregation, Cost Calculations, and Mathematical Correctness."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.persistence import persist_usage_event


@pytest.fixture
async def setup_aggregation_data(async_client: AsyncClient, db_session: AsyncSession):
    # Setup Tenant and 2 Projects
    t_res = await async_client.post(
        "/api/v1/tenants",
        json={"name": "Agg Corp", "slug": f"agg-{uuid.uuid4().hex[:6]}"},
    )
    tenant_id = t_res.json()["id"]

    p1_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "Frontend App", "slug": f"fe-{uuid.uuid4().hex[:6]}"},
    )
    p1_id = p1_res.json()["id"]

    p2_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "Backend Service", "slug": f"be-{uuid.uuid4().hex[:6]}"},
    )
    p2_id = p2_res.json()["id"]

    # Admin Key
    k_res = await async_client.post(
        f"/api/v1/projects/{p1_id}/api-keys", json={"name": "Admin Key"}
    )
    admin_key = k_res.json()["key"]

    now = datetime.now(timezone.utc)

    # 1. Event 1: Project 1, OpenAI gpt-4o, Success, Cost $1.00 (1_000_000 microdollars)
    ev1 = UsageEventPayload(
        request_id="req_agg_1",
        tenant_id=uuid.UUID(tenant_id),
        project_id=uuid.UUID(p1_id),
        provider="openai",
        model="gpt-4o",
        status="success",
        input_tokens=100,
        output_tokens=200,
        total_tokens=300,
        actual_cost=1_000_000,
        timestamp=now - timedelta(hours=2),
    )
    await persist_usage_event(db_session, ev1)

    # 2. Event 2: Project 1, Anthropic claude-3-haiku, Success, Cost $0.50 (500_000 microdollars)
    ev2 = UsageEventPayload(
        request_id="req_agg_2",
        tenant_id=uuid.UUID(tenant_id),
        project_id=uuid.UUID(p1_id),
        provider="anthropic",
        model="claude-3-haiku",
        status="success",
        input_tokens=50,
        output_tokens=150,
        total_tokens=200,
        actual_cost=500_000,
        timestamp=now - timedelta(hours=1),
    )
    await persist_usage_event(db_session, ev2)

    # 3. Event 3: Project 2, OpenAI gpt-4o, Provider Failure, Cost $0.00
    ev3 = UsageEventPayload(
        request_id="req_agg_3",
        tenant_id=uuid.UUID(tenant_id),
        project_id=uuid.UUID(p2_id),
        provider="openai",
        model="gpt-4o",
        status="provider_failure",
        input_tokens=80,
        output_tokens=0,
        total_tokens=80,
        actual_cost=0,
        timestamp=now - timedelta(minutes=30),
    )
    await persist_usage_event(db_session, ev3)

    # 4. Event 4: Project 2, Anthropic claude-3-haiku, Success, Cost $2.00 (2_000_000 microdollars)
    ev4 = UsageEventPayload(
        request_id="req_agg_4",
        tenant_id=uuid.UUID(tenant_id),
        project_id=uuid.UUID(p2_id),
        provider="anthropic",
        model="claude-3-haiku",
        status="success",
        input_tokens=400,
        output_tokens=600,
        total_tokens=1000,
        actual_cost=2_000_000,
        timestamp=now - timedelta(minutes=10),
    )
    await persist_usage_event(db_session, ev4)

    # 5. Out of range event: 40 days ago ($10.00)
    ev_old = UsageEventPayload(
        request_id="req_agg_old",
        tenant_id=uuid.UUID(tenant_id),
        project_id=uuid.UUID(p1_id),
        provider="openai",
        model="gpt-4o",
        status="success",
        input_tokens=1000,
        output_tokens=2000,
        total_tokens=3000,
        actual_cost=10_000_000,
        timestamp=now - timedelta(days=40),
    )
    await persist_usage_event(db_session, ev_old)

    await db_session.commit()

    return {
        "tenant_id": tenant_id,
        "project_1_id": p1_id,
        "project_2_id": p2_id,
        "headers": {"Authorization": f"Bearer {admin_key}"},
        "ev1_payload": ev1,
    }


@pytest.mark.asyncio
async def test_overview_aggregation_math(async_client: AsyncClient, setup_aggregation_data):
    """
    Verify 24h overview arithmetic:
    Total requests: 4 (events 1..4; event 5 is 40 days old)
    Success: 3, Failures: 1
    Total tokens: 300 + 200 + 80 + 1000 = 1580
    Total actual cost: 1.00 + 0.50 + 0.00 + 2.00 = $3.50 (3_500_000 microdollars)
    Error rate: 1/4 = 0.25 (25%)
    """
    data = setup_aggregation_data
    res = await async_client.get("/api/v1/dashboard/overview?range=24h", headers=data["headers"])
    assert res.status_code == 200
    ov = res.json()

    assert ov["total_requests"] == 4
    assert ov["total_tokens"] == 1580
    assert ov["actual_cost_microdollars"] == 3_500_000
    assert ov["actual_cost_usd"] == 3.5
    assert ov["provider_failures"] == 1
    assert ov["error_rate"] == 0.25
    assert ov["active_models_count"] == 2
    assert ov["active_providers_count"] == 2


@pytest.mark.asyncio
async def test_project_filter_aggregation(async_client: AsyncClient, setup_aggregation_data):
    """Filtering by project_id scopes all metrics strictly to that project."""
    data = setup_aggregation_data
    p1_id = data["project_1_id"]

    res = await async_client.get(
        f"/api/v1/dashboard/overview?project_id={p1_id}&range=24h",
        headers=data["headers"],
    )
    assert res.status_code == 200
    ov = res.json()

    # Project 1 has events 1 ($1.00) and 2 ($0.50)
    assert ov["total_requests"] == 2
    assert ov["total_tokens"] == 500
    assert ov["actual_cost_microdollars"] == 1_500_000
    assert ov["actual_cost_usd"] == 1.5
    assert ov["provider_failures"] == 0


@pytest.mark.asyncio
async def test_cost_breakdowns_math(async_client: AsyncClient, setup_aggregation_data):
    """Verify costs breakdown by model, provider, and project."""
    data = setup_aggregation_data
    res = await async_client.get("/api/v1/dashboard/costs?range=24h", headers=data["headers"])
    assert res.status_code == 200
    costs = res.json()

    assert costs["total_cost_microdollars"] == 3_500_000
    assert costs["total_cost_usd"] == 3.5

    # By provider:
    # Anthropic: ev2 ($0.50) + ev4 ($2.00) = $2.50
    # OpenAI: ev1 ($1.00) + ev3 ($0.00) = $1.00
    prov_map = {item["name"]: item["cost_microdollars"] for item in costs["by_provider"]}
    assert prov_map["anthropic"] == 2_500_000
    assert prov_map["openai"] == 1_000_000

    # By model:
    # claude-3-haiku: 2_500_000
    # gpt-4o: 1_000_000
    model_map = {item["name"]: item["cost_microdollars"] for item in costs["by_model"]}
    assert model_map["claude-3-haiku"] == 2_500_000
    assert model_map["gpt-4o"] == 1_000_000

    # By project:
    # Frontend App: $1.50
    # Backend Service: $2.00
    proj_map = {item["name"]: item["cost_microdollars"] for item in costs["by_project"]}
    assert proj_map["Backend Service"] == 2_000_000
    assert proj_map["Frontend App"] == 1_500_000


@pytest.mark.asyncio
async def test_duplicate_event_does_not_double_count(
    async_client: AsyncClient, setup_aggregation_data, db_session: AsyncSession
):
    """Idempotency check: Re-persisting the same event does not affect aggregation totals."""
    data = setup_aggregation_data
    ev1 = data["ev1_payload"]

    # Re-persist the exact same event
    is_inserted = await persist_usage_event(db_session, ev1)
    assert not is_inserted, "Duplicate event must return False"
    await db_session.commit()

    # Query overview again
    res = await async_client.get("/api/v1/dashboard/overview?range=24h", headers=data["headers"])
    ov = res.json()
    assert ov["total_requests"] == 4
    assert ov["actual_cost_microdollars"] == 3_500_000
