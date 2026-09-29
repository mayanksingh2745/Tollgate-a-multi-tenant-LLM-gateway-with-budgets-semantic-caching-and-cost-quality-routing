import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_duplicate_tenant_slug_rejected(async_client: AsyncClient):
    res1 = await async_client.post(
        "/api/v1/tenants", json={"name": "Tenant One", "slug": "unique-slug"}
    )
    assert res1.status_code == 201

    # Duplicate slug must fail with 409 Conflict
    res2 = await async_client.post(
        "/api/v1/tenants", json={"name": "Tenant Two", "slug": "unique-slug"}
    )
    assert res2.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_project_slug_within_tenant_rejected(async_client: AsyncClient):
    t_res = await async_client.post("/api/v1/tenants", json={"name": "Tenant One", "slug": "t-one"})
    tenant1_id = t_res.json()["id"]

    t2_res = await async_client.post(
        "/api/v1/tenants", json={"name": "Tenant Two", "slug": "t-two"}
    )
    tenant2_id = t2_res.json()["id"]

    # Create project 1 in tenant 1
    p1 = await async_client.post(
        f"/api/v1/tenants/{tenant1_id}/projects", json={"name": "Mobile App", "slug": "mobile"}
    )
    assert p1.status_code == 201

    # Duplicate project slug in same tenant MUST fail with 409 Conflict
    p2 = await async_client.post(
        f"/api/v1/tenants/{tenant1_id}/projects", json={"name": "Mobile Web", "slug": "mobile"}
    )
    assert p2.status_code == 409

    # Same project slug in DIFFERENT tenant MUST succeed
    p3 = await async_client.post(
        f"/api/v1/tenants/{tenant2_id}/projects", json={"name": "Mobile App", "slug": "mobile"}
    )
    assert p3.status_code == 201


@pytest.mark.asyncio
async def test_duplicate_user_email_within_tenant_rejected(async_client: AsyncClient):
    t_res = await async_client.post(
        "/api/v1/tenants", json={"name": "Tenant Alpha", "slug": "t-alpha"}
    )
    tenant_id = t_res.json()["id"]

    u1 = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={"name": "User 1", "email": "admin@alpha.com", "password": "Password123!"},
    )
    assert u1.status_code == 201

    # Duplicate email in same tenant (case insensitive) MUST fail with 409
    u2 = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={"name": "User 2", "email": "ADMIN@ALPHA.COM", "password": "Password123!"},
    )
    assert u2.status_code == 409
