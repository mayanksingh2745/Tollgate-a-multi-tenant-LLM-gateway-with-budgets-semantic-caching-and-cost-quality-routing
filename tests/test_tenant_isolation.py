import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_tenant_isolation_matrix(async_client: AsyncClient):
    # 1. Create Tenant A + Project A + API Key A
    t_a = await async_client.post("/api/v1/tenants", json={"name": "Tenant A", "slug": "tenant-a"})
    tenant_a_id = t_a.json()["id"]

    p_a = await async_client.post(f"/api/v1/tenants/{tenant_a_id}/projects", json={"name": "Project A", "slug": "proj-a"})
    project_a_id = p_a.json()["id"]

    k_a = await async_client.post(f"/api/v1/projects/{project_a_id}/api-keys", json={"name": "Key A"})
    key_a_raw = k_a.json()["key"]
    key_a_id = k_a.json()["id"]

    headers_a = {"Authorization": f"Bearer {key_a_raw}"}

    # 2. Create Tenant B + Project B + API Key B
    t_b = await async_client.post("/api/v1/tenants", json={"name": "Tenant B", "slug": "tenant-b"})
    tenant_b_id = t_b.json()["id"]

    p_b = await async_client.post(f"/api/v1/tenants/{tenant_b_id}/projects", json={"name": "Project B", "slug": "proj-b"})
    project_b_id = p_b.json()["id"]

    k_b = await async_client.post(f"/api/v1/projects/{project_b_id}/api-keys", json={"name": "Key B"})
    key_b_raw = k_b.json()["key"]
    key_b_id = k_b.json()["id"]

    headers_b = {"Authorization": f"Bearer {key_b_raw}"}

    # -------------------------------------------------------------
    # MATRIX VERIFICATION 1: Tenant A API Key
    # -------------------------------------------------------------
    # Key A -> Tenant A resources (ALLOWED)
    res = await async_client.get(f"/api/v1/tenants/{tenant_a_id}", headers=headers_a)
    assert res.status_code == 200

    res = await async_client.get(f"/api/v1/tenants/{tenant_a_id}/projects/{project_a_id}", headers=headers_a)
    assert res.status_code == 200

    # Key A -> Tenant B resources (DENIED / 404 NOT FOUND)
    res = await async_client.get(f"/api/v1/tenants/{tenant_b_id}", headers=headers_a)
    assert res.status_code == 404

    res = await async_client.get(f"/api/v1/tenants/{tenant_b_id}/projects", headers=headers_a)
    assert res.status_code == 404

    res = await async_client.get(f"/api/v1/tenants/{tenant_b_id}/projects/{project_b_id}", headers=headers_a)
    assert res.status_code == 404

    res = await async_client.delete(f"/api/v1/api-keys/{key_b_id}", headers=headers_a)
    assert res.status_code == 404

    # -------------------------------------------------------------
    # MATRIX VERIFICATION 2: Tenant B API Key
    # -------------------------------------------------------------
    # Key B -> Tenant B resources (ALLOWED)
    res = await async_client.get(f"/api/v1/tenants/{tenant_b_id}", headers=headers_b)
    assert res.status_code == 200

    res = await async_client.get(f"/api/v1/tenants/{tenant_b_id}/projects/{project_b_id}", headers=headers_b)
    assert res.status_code == 200

    # Key B -> Tenant A resources (DENIED / 404 NOT FOUND)
    res = await async_client.get(f"/api/v1/tenants/{tenant_a_id}", headers=headers_b)
    assert res.status_code == 404

    res = await async_client.get(f"/api/v1/tenants/{tenant_a_id}/projects", headers=headers_b)
    assert res.status_code == 404

    res = await async_client.get(f"/api/v1/tenants/{tenant_a_id}/projects/{project_a_id}", headers=headers_b)
    assert res.status_code == 404

    res = await async_client.delete(f"/api/v1/api-keys/{key_a_id}", headers=headers_b)
    assert res.status_code == 404
