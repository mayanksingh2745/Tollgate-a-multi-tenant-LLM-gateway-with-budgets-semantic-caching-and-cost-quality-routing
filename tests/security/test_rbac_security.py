import pytest
from httpx import AsyncClient

from tests.security.security_fixtures import create_security_tenant_fixture


@pytest.mark.asyncio
async def test_rbac_owner_and_admin_capabilities(async_client: AsyncClient):
    """Owner and Admin roles must be permitted to perform key, budget, and cache actions."""
    fixture = await create_security_tenant_fixture(async_client, "rbac1")

    # 1. Admin can create API key
    k_res = await async_client.post(
        f"/api/v1/projects/{fixture.project_id}/api-keys",
        headers={"Authorization": f"Bearer {fixture.admin_api_key}"},
        json={"name": "New Admin Key", "user_id": str(fixture.admin_user_id)},
    )
    assert k_res.status_code == 201

    # 2. Owner can update budget
    b_res = await async_client.put(
        f"/api/v1/tenants/{fixture.tenant_id}/budget",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={"daily_budget_microdollars": 5_000_000, "monthly_budget_microdollars": 50_000_000},
    )
    assert b_res.status_code == 200

    # 3. Admin can update project budget
    pb_res = await async_client.put(
        f"/api/v1/projects/{fixture.project_id}/budget",
        headers={"Authorization": f"Bearer {fixture.admin_api_key}"},
        json={"daily_budget_microdollars": 1_000_000, "monthly_budget_microdollars": 10_000_000},
    )
    assert pb_res.status_code == 200

    # 4. Admin can invalidate project cache
    c_res = await async_client.delete(
        f"/api/v1/projects/{fixture.project_id}/cache",
        headers={"Authorization": f"Bearer {fixture.admin_api_key}"},
    )
    assert c_res.status_code == 200
    assert c_res.json()["status"] == "success"


@pytest.mark.asyncio
async def test_rbac_viewer_denied_mutations(async_client: AsyncClient):
    """Viewer role must be rejected with 403 Forbidden on all state-mutating endpoints."""
    fixture = await create_security_tenant_fixture(async_client, "rbac2")
    headers = {"Authorization": f"Bearer {fixture.viewer_api_key}"}

    # 1. Viewer cannot create API keys
    k_res = await async_client.post(
        f"/api/v1/projects/{fixture.project_id}/api-keys",
        headers=headers,
        json={"name": "Disallowed Viewer Key"},
    )
    assert k_res.status_code == 403
    assert "detail" in k_res.json()

    # 2. Viewer cannot update tenant budget
    b_res = await async_client.put(
        f"/api/v1/tenants/{fixture.tenant_id}/budget",
        headers=headers,
        json={"daily_budget_microdollars": 100},
    )
    assert b_res.status_code == 403

    # 3. Viewer cannot update project budget
    pb_res = await async_client.put(
        f"/api/v1/projects/{fixture.project_id}/budget",
        headers=headers,
        json={"daily_budget_microdollars": 100},
    )
    assert pb_res.status_code == 403

    # 4. Viewer cannot invalidate cache
    c_res = await async_client.delete(
        f"/api/v1/projects/{fixture.project_id}/cache",
        headers=headers,
    )
    assert c_res.status_code == 403

    # 5. Viewer cannot create projects
    p_res = await async_client.post(
        f"/api/v1/tenants/{fixture.tenant_id}/projects",
        headers=headers,
        json={"name": "Viewer Project", "slug": "viewer-proj"},
    )
    assert p_res.status_code == 403


@pytest.mark.asyncio
async def test_rbac_viewer_allowed_read_telemetry(async_client: AsyncClient):
    """Viewer role must have read-only access to dashboard and usage telemetry."""
    fixture = await create_security_tenant_fixture(async_client, "rbac3")
    headers = {"Authorization": f"Bearer {fixture.viewer_api_key}"}

    # 1. Dashboard Me
    me_res = await async_client.get("/api/v1/dashboard/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["role"] == "viewer"

    # 2. Dashboard Overview
    ov_res = await async_client.get("/api/v1/dashboard/overview", headers=headers)
    assert ov_res.status_code == 200

    # 3. Dashboard Requests
    req_res = await async_client.get("/api/v1/dashboard/requests", headers=headers)
    assert req_res.status_code == 200

    # 4. Dashboard Usage Time-Series
    us_res = await async_client.get("/api/v1/dashboard/usage", headers=headers)
    assert us_res.status_code == 200

    # 5. Dashboard Costs
    cost_res = await async_client.get("/api/v1/dashboard/costs", headers=headers)
    assert cost_res.status_code == 200

    # 6. Dashboard Budgets
    bd_res = await async_client.get("/api/v1/dashboard/budgets", headers=headers)
    assert bd_res.status_code == 200

    # 7. Usage Events API
    u_res = await async_client.get("/api/v1/usage", headers=headers)
    assert u_res.status_code == 200


@pytest.mark.asyncio
async def test_rbac_unauthorized_access(async_client: AsyncClient):
    """Unauthenticated calls to protected operations must receive 401 Unauthorized."""
    endpoints = [
        ("GET", "/api/v1/dashboard/me"),
        ("GET", "/api/v1/dashboard/overview"),
        ("GET", "/api/v1/usage"),
        ("DELETE", "/api/v1/projects/00000000-0000-0000-0000-000000000000/cache"),
        ("PUT", "/api/v1/tenants/00000000-0000-0000-0000-000000000000/budget"),
    ]
    for method, path in endpoints:
        if method == "GET":
            res = await async_client.get(path)
        elif method == "DELETE":
            res = await async_client.delete(path)
        elif method == "PUT":
            res = await async_client.put(path, json={})
        assert res.status_code == 401, f"Failed for {method} {path}"
