import pytest
from httpx import AsyncClient


@pytest.fixture
async def setup_two_tenants(async_client: AsyncClient):
    # Tenant A
    t_a = (
        await async_client.post("/api/v1/tenants", json={"name": "Tenant A", "slug": "tenant-a"})
    ).json()
    p_a = (
        await async_client.post(
            f"/api/v1/tenants/{t_a['id']}/projects", json={"name": "Proj A", "slug": "proj-a"}
        )
    ).json()
    k_a = (
        await async_client.post(f"/api/v1/projects/{p_a['id']}/api-keys", json={"name": "Key A"})
    ).json()

    # Tenant B
    t_b = (
        await async_client.post("/api/v1/tenants", json={"name": "Tenant B", "slug": "tenant-b"})
    ).json()
    p_b = (
        await async_client.post(
            f"/api/v1/tenants/{t_b['id']}/projects", json={"name": "Proj B", "slug": "proj-b"}
        )
    ).json()
    k_b = (
        await async_client.post(f"/api/v1/projects/{p_b['id']}/api-keys", json={"name": "Key B"})
    ).json()

    return {
        "t_a": t_a,
        "p_a": p_a,
        "headers_a": {"Authorization": f"Bearer {k_a['key']}"},
        "t_b": t_b,
        "p_b": p_b,
        "headers_b": {"Authorization": f"Bearer {k_b['key']}"},
    }


@pytest.mark.asyncio
async def test_budget_tenant_isolation_enforcement(async_client: AsyncClient, setup_two_tenants):
    data = setup_two_tenants

    # Set Tenant A budget to $0.0001 (100 microdollars)
    set_a = await async_client.put(
        f"/api/v1/tenants/{data['t_a']['id']}/budget",
        headers=data["headers_a"],
        json={"monthly_budget_microdollars": 100},
    )
    assert set_a.status_code == 200

    # Set Tenant B budget to $100.00 (100,000,000 microdollars)
    set_b = await async_client.put(
        f"/api/v1/tenants/{data['t_b']['id']}/budget",
        headers=data["headers_b"],
        json={"monthly_budget_microdollars": 100_000_000},
    )
    assert set_b.status_code == 200

    payload = {"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]}

    # Tenant A request should fail with 402 Budget Exceeded
    r_a = await async_client.post("/v1/chat/completions", headers=data["headers_a"], json=payload)
    assert r_a.status_code == 402
    assert r_a.json()["error"]["code"] == "budget_exceeded"

    # Tenant B request should succeed!
    r_b = await async_client.post("/v1/chat/completions", headers=data["headers_b"], json=payload)
    assert r_b.status_code == 200


@pytest.mark.asyncio
async def test_cross_tenant_budget_modification_forbidden(
    async_client: AsyncClient, setup_two_tenants
):
    data = setup_two_tenants

    # Tenant A attempts to read Tenant B's budget -> 404 Not Found (isolated)
    get_res = await async_client.get(
        f"/api/v1/tenants/{data['t_b']['id']}/budget",
        headers=data["headers_a"],
    )
    assert get_res.status_code == 404

    # Tenant A attempts to update Tenant B's budget -> 404 Not Found (isolated)
    put_res = await async_client.put(
        f"/api/v1/tenants/{data['t_b']['id']}/budget",
        headers=data["headers_a"],
        json={"monthly_budget_microdollars": 500},
    )
    assert put_res.status_code == 404
