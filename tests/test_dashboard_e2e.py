"""End-to-End Dashboard Flow Test:
Login -> Dashboard Overview -> Select Project -> Usage Time Series -> Cost Breakdown -> Requests Explorer -> Request Detail.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.persistence import persist_usage_event


@pytest.mark.asyncio
async def test_dashboard_end_to_end_journey(async_client: AsyncClient, db_session: AsyncSession):
    # 1. Setup Tenant, 2 Projects, and Admin User
    t_res = await async_client.post(
        "/api/v1/tenants",
        json={"name": "Acme Global", "slug": f"acme-{uuid.uuid4().hex[:6]}"},
    )
    assert t_res.status_code == 201
    tenant_id = t_res.json()["id"]

    p1_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "Web Platform", "slug": f"web-{uuid.uuid4().hex[:6]}"},
    )
    assert p1_res.status_code == 201
    project_1_id = p1_res.json()["id"]

    p2_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "Mobile Backend", "slug": f"mob-{uuid.uuid4().hex[:6]}"},
    )
    assert p2_res.status_code == 201
    project_2_id = p2_res.json()["id"]

    user_email = f"lead-{uuid.uuid4().hex[:6]}@acme.com"
    user_password = "SuperSecurePassword123!"
    u_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "name": "Acme Tech Lead",
            "email": user_email,
            "password": user_password,
            "role": "admin",
        },
    )
    assert u_res.status_code == 201

    # 2. Seed 3 deterministic usage events
    now = datetime.now(timezone.utc)
    ev1 = UsageEventPayload(
        request_id="req_e2e_web_001",
        tenant_id=uuid.UUID(tenant_id),
        project_id=uuid.UUID(project_1_id),
        provider="openai",
        model="gpt-4o",
        status="success",
        input_tokens=150,
        output_tokens=250,
        total_tokens=400,
        actual_cost=2_000_000,  # $2.00
        latency_ms=120.0,
        router_route="strong",
        cache_status="MISS",
        timestamp=now - timedelta(hours=1),
    )
    await persist_usage_event(db_session, ev1)

    ev2 = UsageEventPayload(
        request_id="req_e2e_web_002",
        tenant_id=uuid.UUID(tenant_id),
        project_id=uuid.UUID(project_1_id),
        provider="openai",
        model="mock-fast",
        status="success",
        input_tokens=80,
        output_tokens=70,
        total_tokens=150,
        actual_cost=300_000,  # $0.30
        latency_ms=65.0,
        router_route="cheap",
        cache_status="MISS",
        timestamp=now - timedelta(minutes=45),
    )
    await persist_usage_event(db_session, ev2)

    ev3 = UsageEventPayload(
        request_id="req_e2e_mob_001",
        tenant_id=uuid.UUID(tenant_id),
        project_id=uuid.UUID(project_2_id),
        provider="anthropic",
        model="claude-3-haiku",
        status="provider_failure",
        input_tokens=50,
        output_tokens=0,
        total_tokens=50,
        actual_cost=0,
        latency_ms=850.0,
        router_route="passthrough",
        cache_status="BYPASS",
        timestamp=now - timedelta(minutes=20),
    )
    await persist_usage_event(db_session, ev3)
    await db_session.commit()

    # STEP A: Login
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": user_email, "password": user_password},
    )
    assert login_res.status_code == 200
    auth_data = login_res.json()
    token = auth_data["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert auth_data["user"]["name"] == "Acme Tech Lead"
    assert auth_data["user"]["role"] == "admin"
    assert len(auth_data["user"]["projects"]) >= 2

    # STEP B: Dashboard /me
    me_res = await async_client.get("/api/v1/dashboard/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["tenant_name"] == "Acme Global"

    # STEP C: Overview across all projects
    ov_res = await async_client.get("/api/v1/dashboard/overview?range=24h", headers=headers)
    assert ov_res.status_code == 200
    ov = ov_res.json()
    assert ov["total_requests"] == 3
    assert ov["total_tokens"] == 600
    assert ov["actual_cost_microdollars"] == 2_300_000
    assert ov["actual_cost_usd"] == 2.3
    assert ov["provider_failures"] == 1
    assert ov["cheap_routing_percentage"] == 50.0  # 1 cheap, 1 strong -> 50%
    assert ov["strong_routing_percentage"] == 50.0

    # STEP D: Project Selector -> Scope to Web Platform (project_1)
    p1_ov_res = await async_client.get(
        f"/api/v1/dashboard/overview?project_id={project_1_id}&range=24h", headers=headers
    )
    assert p1_ov_res.status_code == 200
    p1_ov = p1_ov_res.json()
    assert p1_ov["total_requests"] == 2
    assert p1_ov["total_tokens"] == 550
    assert p1_ov["actual_cost_microdollars"] == 2_300_000
    assert p1_ov["provider_failures"] == 0

    # STEP E: Usage Time-Series
    usage_res = await async_client.get(
        f"/api/v1/dashboard/usage?project_id={project_1_id}&range=24h", headers=headers
    )
    assert usage_res.status_code == 200
    usage = usage_res.json()
    assert len(usage["points"]) >= 1
    tot_pts_reqs = sum(pt["requests"] for pt in usage["points"])
    assert tot_pts_reqs == 2

    # STEP F: Cost Breakdown
    cost_res = await async_client.get("/api/v1/dashboard/costs?range=24h", headers=headers)
    assert cost_res.status_code == 200
    costs = cost_res.json()
    assert costs["total_cost_microdollars"] == 2_300_000
    assert len(costs["by_project"]) == 2
    assert costs["by_project"][0]["name"] == "Web Platform"

    # STEP G: Requests Explorer
    reqs_res = await async_client.get(
        "/api/v1/dashboard/requests?page=1&page_size=10", headers=headers
    )
    assert reqs_res.status_code == 200
    reqs_data = reqs_res.json()
    assert reqs_data["total"] == 3
    req_ids = [r["request_id"] for r in reqs_data["items"]]
    assert "req_e2e_web_001" in req_ids
    assert "req_e2e_web_002" in req_ids
    assert "req_e2e_mob_001" in req_ids

    # STEP H: Request Detail View
    detail_res = await async_client.get(
        "/api/v1/dashboard/requests/req_e2e_web_001", headers=headers
    )
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["request_id"] == "req_e2e_web_001"
    assert detail["project_name"] == "Web Platform"
    assert detail["model"] == "gpt-4o"
    assert detail["provider"] == "openai"
    assert detail["status"] == "success"
    assert detail["total_tokens"] == 400
    assert detail["actual_cost_microdollars"] == 2_000_000
    assert detail["router_route"] == "strong"
    assert detail["cache_status"] == "MISS"
