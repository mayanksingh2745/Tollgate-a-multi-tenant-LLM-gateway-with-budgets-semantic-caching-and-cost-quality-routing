import pytest
from httpx import AsyncClient

from tests.security.security_fixtures import create_security_tenant_fixture


@pytest.mark.asyncio
async def test_idor_tampered_tenant_in_usage_query(async_client: AsyncClient):
    """Client attempting to query usage for a different tenant ID must be denied (403/404)."""
    tenant_a = await create_security_tenant_fixture(async_client, "idor1a")
    tenant_b = await create_security_tenant_fixture(async_client, "idor1b")

    res = await async_client.get(
        f"/api/v1/usage?tenant_id={tenant_b.tenant_id}",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
    )
    assert res.status_code in (403, 404)
    assert "Access denied" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_idor_tampered_project_in_usage_query(async_client: AsyncClient):
    """Client attempting to query usage for a different project ID must be denied."""
    tenant_a = await create_security_tenant_fixture(async_client, "idor2a")
    tenant_b = await create_security_tenant_fixture(async_client, "idor2b")

    res = await async_client.get(
        f"/api/v1/usage?project_id={tenant_b.project_id}",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
    )
    assert res.status_code in (403, 404)


@pytest.mark.asyncio
async def test_idor_tampered_tenant_in_budget_endpoints(async_client: AsyncClient):
    """Client attempting to modify budget by tampering tenant_id in path must be rejected."""
    tenant_a = await create_security_tenant_fixture(async_client, "idor3a")
    tenant_b = await create_security_tenant_fixture(async_client, "idor3b")

    res = await async_client.put(
        f"/api/v1/tenants/{tenant_b.tenant_id}/budget",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
        json={"daily_budget_microdollars": 500},
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Tenant not found."


@pytest.mark.asyncio
async def test_idor_tampered_project_in_budget_endpoints(async_client: AsyncClient):
    """Client attempting to read or modify project budget of another tenant."""
    tenant_a = await create_security_tenant_fixture(async_client, "idor4a")
    tenant_b = await create_security_tenant_fixture(async_client, "idor4b")

    res = await async_client.get(
        f"/api/v1/projects/{tenant_b.project_id}/budget",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Project not found."


@pytest.mark.asyncio
async def test_idor_dashboard_filter_tampering(async_client: AsyncClient):
    """Passing another tenant's project_id to dashboard filters must yield 404 or empty results."""
    tenant_a = await create_security_tenant_fixture(async_client, "idor5a")
    tenant_b = await create_security_tenant_fixture(async_client, "idor5b")

    res = await async_client.get(
        f"/api/v1/dashboard/overview?project_id={tenant_b.project_id}",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
    )
    assert res.status_code == 404
    assert "not found or not in tenant" in res.json().get("detail", "")
