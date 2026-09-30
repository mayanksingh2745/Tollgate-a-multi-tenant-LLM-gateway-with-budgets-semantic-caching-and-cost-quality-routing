"""Tests for Dashboard Authentication, RBAC, and strict Tenant Isolation."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.persistence import persist_usage_event


@pytest.fixture
async def setup_tenants_and_users(async_client: AsyncClient, db_session: AsyncSession):
    # 1. Tenant A
    t_a_res = await async_client.post(
        "/api/v1/tenants",
        json={"name": "Tenant Alpha", "slug": f"alpha-{uuid.uuid4().hex[:6]}"},
    )
    t_a_id = t_a_res.json()["id"]

    p_a_res = await async_client.post(
        f"/api/v1/tenants/{t_a_id}/projects",
        json={"name": "Alpha Proj 1", "slug": f"p1-{uuid.uuid4().hex[:6]}"},
    )
    p_a1_id = p_a_res.json()["id"]

    p_a2_res = await async_client.post(
        f"/api/v1/tenants/{t_a_id}/projects",
        json={"name": "Alpha Proj 2", "slug": f"p2-{uuid.uuid4().hex[:6]}"},
    )
    p_a2_id = p_a2_res.json()["id"]

    # Admin Key for Tenant A
    k_a_admin = await async_client.post(
        f"/api/v1/projects/{p_a1_id}/api-keys", json={"name": "Alpha Admin Key"}
    )
    admin_key_a = k_a_admin.json()["key"]

    # Viewer User for Tenant A
    u_a_viewer = await async_client.post(
        f"/api/v1/tenants/{t_a_id}/users",
        json={
            "name": "Alpha Viewer",
            "email": f"viewer-{uuid.uuid4().hex[:6]}@alpha.com",
            "password": "Password123!",
            "role": "viewer",
        },
    )
    viewer_id_a = u_a_viewer.json()["id"]

    k_a_viewer = await async_client.post(
        f"/api/v1/projects/{p_a1_id}/api-keys",
        json={"name": "Alpha Viewer Key", "user_id": viewer_id_a},
    )
    viewer_key_a = k_a_viewer.json()["key"]

    # 2. Tenant B
    t_b_res = await async_client.post(
        "/api/v1/tenants",
        json={"name": "Tenant Beta", "slug": f"beta-{uuid.uuid4().hex[:6]}"},
    )
    t_b_id = t_b_res.json()["id"]

    p_b_res = await async_client.post(
        f"/api/v1/tenants/{t_b_id}/projects",
        json={"name": "Beta Proj", "slug": f"beta-p-{uuid.uuid4().hex[:6]}"},
    )
    p_b_id = p_b_res.json()["id"]

    k_b_admin = await async_client.post(
        f"/api/v1/projects/{p_b_id}/api-keys", json={"name": "Beta Admin Key"}
    )
    admin_key_b = k_b_admin.json()["key"]

    # Seed an event in Tenant A
    ev_a = UsageEventPayload(
        request_id="req_alpha_001",
        tenant_id=uuid.UUID(t_a_id),
        project_id=uuid.UUID(p_a1_id),
        provider="openai",
        model="gpt-4o",
        status="success",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        actual_cost=1_500_000,  # $1.50
    )
    await persist_usage_event(db_session, ev_a)

    # Seed an event in Tenant B
    ev_b = UsageEventPayload(
        request_id="req_beta_001",
        tenant_id=uuid.UUID(t_b_id),
        project_id=uuid.UUID(p_b_id),
        provider="anthropic",
        model="claude-3-opus",
        status="success",
        input_tokens=200,
        output_tokens=100,
        total_tokens=300,
        actual_cost=4_500_000,  # $4.50
    )
    await persist_usage_event(db_session, ev_b)
    await db_session.commit()

    return {
        "tenant_a_id": t_a_id,
        "project_a1_id": p_a1_id,
        "project_a2_id": p_a2_id,
        "headers_a_admin": {"Authorization": f"Bearer {admin_key_a}"},
        "headers_a_viewer": {"Authorization": f"Bearer {viewer_key_a}"},
        "tenant_b_id": t_b_id,
        "project_b_id": p_b_id,
        "headers_b_admin": {"Authorization": f"Bearer {admin_key_b}"},
        "viewer_email": u_a_viewer.json()["email"],
    }


@pytest.mark.asyncio
async def test_unauthenticated_requests_are_denied(async_client: AsyncClient):
    """Endpoints require authentication and return 401 when unauthenticated."""
    endpoints = [
        "/api/v1/dashboard/me",
        "/api/v1/dashboard/overview",
        "/api/v1/dashboard/usage",
        "/api/v1/dashboard/costs",
        "/api/v1/dashboard/budgets",
        "/api/v1/dashboard/models",
        "/api/v1/dashboard/providers",
        "/api/v1/dashboard/cache",
        "/api/v1/dashboard/router",
        "/api/v1/dashboard/requests",
        "/api/v1/dashboard/projects",
        "/api/v1/dashboard/api-keys",
    ]
    for ep in endpoints:
        res = await async_client.get(ep)
        assert res.status_code == 401, f"Endpoint {ep} should be 401 unauthenticated"


@pytest.mark.asyncio
async def test_viewer_role_can_read_analytics_but_cannot_modify(
    async_client: AsyncClient, setup_tenants_and_users
):
    """
    Viewer role:
    - CAN read all dashboard analytics.
    - CANNOT perform mutating actions like creating/revoking API keys or updating budgets.
    """
    data = setup_tenants_and_users
    viewer_headers = data["headers_a_viewer"]

    # 1. Read operations succeed for Viewer
    res_me = await async_client.get("/api/v1/dashboard/me", headers=viewer_headers)
    assert res_me.status_code == 200
    assert res_me.json()["role"] == "viewer"

    res_ov = await async_client.get("/api/v1/dashboard/overview", headers=viewer_headers)
    assert res_ov.status_code == 200

    res_req = await async_client.get("/api/v1/dashboard/requests", headers=viewer_headers)
    assert res_req.status_code == 200

    # 2. Mutating operations are forbidden for Viewer (403)
    p1 = data["project_a1_id"]
    res_create_key = await async_client.post(
        f"/api/v1/projects/{p1}/api-keys",
        headers=viewer_headers,
        json={"name": "Illegal Viewer Key"},
    )
    assert res_create_key.status_code == 403

    res_budget_update = await async_client.put(
        f"/api/v1/projects/{p1}/budget",
        headers=viewer_headers,
        json={"monthly_budget_microdollars": 50000},
    )
    assert res_budget_update.status_code == 403


@pytest.mark.asyncio
async def test_strict_tenant_isolation(async_client: AsyncClient, setup_tenants_and_users):
    """
    Tenant A caller:
    - Sees Tenant A's usage, costs, models, requests.
    - NEVER sees Tenant B's data.
    """
    data = setup_tenants_and_users
    headers_a = data["headers_a_admin"]
    headers_b = data["headers_b_admin"]

    # 1. Overview check
    ov_a = (await async_client.get("/api/v1/dashboard/overview", headers=headers_a)).json()
    ov_b = (await async_client.get("/api/v1/dashboard/overview", headers=headers_b)).json()

    assert ov_a["total_requests"] == 1
    assert ov_a["actual_cost_microdollars"] == 1_500_000
    assert ov_a["actual_cost_usd"] == 1.5

    assert ov_b["total_requests"] == 1
    assert ov_b["actual_cost_microdollars"] == 4_500_000
    assert ov_b["actual_cost_usd"] == 4.5

    # 2. Requests explorer check
    reqs_a = (await async_client.get("/api/v1/dashboard/requests", headers=headers_a)).json()
    req_ids_a = [r["request_id"] for r in reqs_a["items"]]
    assert "req_alpha_001" in req_ids_a
    assert "req_beta_001" not in req_ids_a

    # 3. Cross-tenant request detail returns 404
    detail_res = await async_client.get(
        "/api/v1/dashboard/requests/req_beta_001", headers=headers_a
    )
    assert detail_res.status_code == 404


@pytest.mark.asyncio
async def test_auth_login_endpoint(async_client: AsyncClient, setup_tenants_and_users):
    """Test user login via email and password returning bearer token."""
    data = setup_tenants_and_users

    # Incorrect password
    bad_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": data["viewer_email"], "password": "WrongPassword!"},
    )
    assert bad_login.status_code == 401

    # Correct credentials
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": data["viewer_email"], "password": "Password123!"},
    )
    assert login_res.status_code == 200
    res_data = login_res.json()
    assert "token" in res_data
    assert res_data["user"]["role"] == "viewer"
    assert res_data["user"]["email"] == data["viewer_email"]

    # Use the returned token to query dashboard
    token_headers = {"Authorization": f"Bearer {res_data['token']}"}
    me_res = await async_client.get("/api/v1/dashboard/me", headers=token_headers)
    assert me_res.status_code == 200
    assert me_res.json()["email"] == data["viewer_email"]
