from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import APIKey
from tollgate_core.security import generate_api_key, hash_api_key


@pytest.mark.asyncio
async def test_api_key_generation_and_hashing():
    raw_key, key_prefix, key_hash = generate_api_key()

    assert raw_key.startswith("tg_live_")
    assert key_prefix == raw_key[:16]
    assert key_hash == hash_api_key(raw_key)
    assert raw_key != key_hash  # Raw secret must never match hash


@pytest.mark.asyncio
async def test_api_key_lifecycle_flow(async_client: AsyncClient, db_session: AsyncSession):
    # 1. Create Tenant
    res = await async_client.post("/api/v1/tenants", json={"name": "Acme Corp", "slug": "acme"})
    assert res.status_code == 201
    tenant_id = res.json()["id"]

    # 2. Create Project
    res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects", json={"name": "Production AI", "slug": "prod-ai"}
    )
    assert res.status_code == 201
    project_id = res.json()["id"]

    # 3. Create API Key
    res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "Primary Key"}
    )
    assert res.status_code == 201
    key_data = res.json()

    assert "key" in key_data
    raw_key = key_data["key"]
    key_id = key_data["id"]
    assert raw_key.startswith("tg_live_")

    # 4. Verify raw key is NOT stored in database
    from uuid import UUID

    db_key = await db_session.get(APIKey, UUID(key_id))
    assert db_key is not None
    assert db_key.key_hash != raw_key
    assert raw_key not in db_key.key_hash

    # 5. GET /api-keys list must NOT reveal raw secret key
    res = await async_client.get(f"/api/v1/projects/{project_id}/api-keys")
    assert res.status_code == 200
    listed_keys = res.json()
    assert len(listed_keys) == 1
    assert "key" not in listed_keys[0]  # Raw key is omitted from list!

    # 6. Authenticate with correct key
    headers = {"Authorization": f"Bearer {raw_key}"}
    res = await async_client.get(f"/api/v1/tenants/{tenant_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["id"] == tenant_id

    # 7. Wrong key fails
    res = await async_client.get(
        f"/api/v1/tenants/{tenant_id}", headers={"Authorization": "Bearer tg_live_invalidkey12345"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid or expired API key"

    # 8. Missing key fails
    res = await async_client.get(f"/api/v1/tenants/{tenant_id}")
    assert res.status_code == 401

    # 9. Malformed header fails
    res = await async_client.get(
        f"/api/v1/tenants/{tenant_id}", headers={"Authorization": f"Basic {raw_key}"}
    )
    assert res.status_code == 401

    # 10. Revoked key fails
    res = await async_client.delete(f"/api/v1/api-keys/{key_id}")
    assert res.status_code == 200
    assert res.json()["status"] == "revoked"

    res = await async_client.get(f"/api/v1/tenants/{tenant_id}", headers=headers)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_api_key_expiration(async_client: AsyncClient):
    # Setup Tenant & Project
    t_res = await async_client.post(
        "/api/v1/tenants", json={"name": "Test Tenant", "slug": "test-t"}
    )
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects", json={"name": "Proj", "slug": "proj"}
    )
    project_id = p_res.json()["id"]

    # Create expired key
    past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        json={"name": "Expired Key", "expires_at": past_time},
    )
    raw_key = k_res.json()["key"]

    # Attempt authentication with expired key
    res = await async_client.get(
        f"/api/v1/tenants/{tenant_id}", headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid or expired API key"


@pytest.mark.asyncio
async def test_api_key_rotation(async_client: AsyncClient):
    # Setup Tenant & Project & Key
    t_res = await async_client.post(
        "/api/v1/tenants", json={"name": "Rotation Tenant", "slug": "rot-t"}
    )
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects", json={"name": "Proj", "slug": "proj"}
    )
    project_id = p_res.json()["id"]

    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "Original Key"}
    )
    old_key_id = k_res.json()["id"]
    old_raw_key = k_res.json()["key"]

    # Verify old key works
    res = await async_client.get(
        f"/api/v1/tenants/{tenant_id}", headers={"Authorization": f"Bearer {old_raw_key}"}
    )
    assert res.status_code == 200

    # Rotate API Key
    rot_res = await async_client.post(f"/api/v1/api-keys/{old_key_id}/rotate")
    assert rot_res.status_code == 200
    new_raw_key = rot_res.json()["key"]
    assert new_raw_key != old_raw_key

    # Old rotated key fails
    res = await async_client.get(
        f"/api/v1/tenants/{tenant_id}", headers={"Authorization": f"Bearer {old_raw_key}"}
    )
    assert res.status_code == 401

    # New rotated key works
    res = await async_client.get(
        f"/api/v1/tenants/{tenant_id}", headers={"Authorization": f"Bearer {new_raw_key}"}
    )
    assert res.status_code == 200
