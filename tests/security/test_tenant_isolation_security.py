import pytest
from httpx import AsyncClient

from tests.security.security_fixtures import create_security_tenant_fixture


@pytest.mark.asyncio
async def test_cross_tenant_project_isolation(async_client: AsyncClient):
    """Tenant A credentials must not be able to get or modify Tenant B's projects."""
    tenant_a = await create_security_tenant_fixture(async_client, "iso1a")
    tenant_b = await create_security_tenant_fixture(async_client, "iso1b")

    # Tenant A attempts to access Tenant B's project details
    res = await async_client.get(
        f"/api/v1/tenants/{tenant_b.tenant_id}/projects/{tenant_b.project_id}",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
    )
    assert res.status_code == 404, f"Expected 404, got {res.status_code}"


@pytest.mark.asyncio
async def test_cross_tenant_api_key_isolation(async_client: AsyncClient):
    """Tenant A credentials must not list or revoke Tenant B's API keys."""
    tenant_a = await create_security_tenant_fixture(async_client, "iso2a")
    tenant_b = await create_security_tenant_fixture(async_client, "iso2b")

    # 1. Tenant A attempts to list Tenant B's keys
    list_res = await async_client.get(
        f"/api/v1/projects/{tenant_b.project_id}/api-keys",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
    )
    assert list_res.status_code == 404

    # 2. Tenant A attempts to create key under Tenant B's project
    create_res = await async_client.post(
        f"/api/v1/projects/{tenant_b.project_id}/api-keys",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
        json={"name": "Attacker Injected Key"},
    )
    assert create_res.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_budget_isolation(async_client: AsyncClient):
    """Tenant A credentials must not read or update Tenant B's budget."""
    tenant_a = await create_security_tenant_fixture(async_client, "iso3a")
    tenant_b = await create_security_tenant_fixture(async_client, "iso3b")

    # Read Tenant B budget
    get_res = await async_client.get(
        f"/api/v1/tenants/{tenant_b.tenant_id}/budget",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
    )
    assert get_res.status_code == 404

    # Update Tenant B budget
    put_res = await async_client.put(
        f"/api/v1/tenants/{tenant_b.tenant_id}/budget",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
        json={"daily_budget_microdollars": 999},
    )
    assert put_res.status_code == 404

    # Read Tenant B project budget
    pget_res = await async_client.get(
        f"/api/v1/projects/{tenant_b.project_id}/budget",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
    )
    assert pget_res.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_cache_invalidation_isolation(async_client: AsyncClient):
    """Tenant A cannot invalidate Tenant B's cache."""
    tenant_a = await create_security_tenant_fixture(async_client, "iso4a")
    tenant_b = await create_security_tenant_fixture(async_client, "iso4b")

    res = await async_client.delete(
        f"/api/v1/projects/{tenant_b.project_id}/cache",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
    )
    assert res.status_code in (403, 404)


@pytest.mark.asyncio
async def test_cross_tenant_usage_and_rollups_isolation(async_client: AsyncClient):
    """Tenant A cannot query Tenant B's usage events or rollups."""
    tenant_a = await create_security_tenant_fixture(async_client, "iso5a")
    tenant_b = await create_security_tenant_fixture(async_client, "iso5b")

    # Generate a chat completion in Tenant B so usage exists
    chat_res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {tenant_b.owner_api_key}"},
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello tenant B"}]},
    )
    assert chat_res.status_code == 200

    # Tenant A attempts to query usage supplying tenant_b ID
    u_res = await async_client.get(
        f"/api/v1/usage?tenant_id={tenant_b.tenant_id}",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
    )
    assert u_res.status_code in (403, 404)

    # Tenant A queries usage without filter: must be empty
    u_a_res = await async_client.get(
        "/api/v1/usage",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
    )
    assert u_a_res.status_code == 200
    assert len(u_a_res.json()["items"]) == 0


@pytest.mark.asyncio
async def test_cross_tenant_dashboard_request_detail_isolation(async_client: AsyncClient):
    """Tenant A cannot retrieve details for a request executed by Tenant B."""
    tenant_a = await create_security_tenant_fixture(async_client, "iso6a")
    tenant_b = await create_security_tenant_fixture(async_client, "iso6b")

    # Execute request in Tenant B
    chat_res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {tenant_b.owner_api_key}"},
        json={"model": "mock-model", "messages": [{"role": "user", "content": "secret question"}]},
    )
    assert chat_res.status_code == 200
    req_id = chat_res.headers.get("X-Request-ID")
    assert req_id is not None

    # Tenant A attempts to get request detail by request_id
    detail_res = await async_client.get(
        f"/api/v1/dashboard/requests/{req_id}",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
    )
    assert detail_res.status_code == 404
    assert detail_res.json()["detail"] == "Request not found or access denied."
