import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import Project, Tenant

from tests.security.security_fixtures import create_security_tenant_fixture


@pytest.mark.asyncio
async def test_auth_valid_key(async_client: AsyncClient):
    """Verify that a valid active API key successfully authenticates."""
    fixture = await create_security_tenant_fixture(async_client, "auth1")

    res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert res.status_code == 200
    assert "choices" in res.json()


@pytest.mark.asyncio
async def test_auth_missing_header(async_client: AsyncClient):
    """Missing Authorization header must return 401 with standard error envelope."""
    res = await async_client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert res.status_code == 401
    data = res.json()
    assert data["detail"] == "Invalid or expired API key"


@pytest.mark.asyncio
async def test_auth_malformed_headers(async_client: AsyncClient):
    """Malformed Authorization headers must safely return 401 without stack trace."""
    malformed_values = [
        "Basic dXNlcjpwYXNz",
        "Bearer",
        "Bearer key1 key2",
        "Token tg_live_12345",
        "Bearer-tg_live_12345",
        "",
    ]
    for val in malformed_values:
        res = await async_client.post(
            "/v1/chat/completions",
            headers={"Authorization": val},
            json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}]},
        )
        assert res.status_code == 401, f"Failed for header: {val}"
        assert res.json()["detail"] == "Invalid or expired API key"


@pytest.mark.asyncio
async def test_auth_wrong_prefix_and_invalid_keys(async_client: AsyncClient):
    """Keys with wrong prefix or invalid entropy must be rejected with 401."""
    invalid_keys = [
        "wrong_prefix_random_secret_token_123456",
        "tg_live_",
        "tg_live_short",
        "tg_test_unrecognized_prefix_abcdef",
        "tg_live_nonexistent_valid_format_key_1234567890abcdef",
    ]
    for key in invalid_keys:
        res = await async_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}]},
        )
        assert res.status_code == 401
        assert res.json()["detail"] == "Invalid or expired API key"


@pytest.mark.asyncio
async def test_auth_revoked_key(async_client: AsyncClient):
    """Revoked keys must immediately fail authentication."""
    fixture = await create_security_tenant_fixture(async_client, "auth2")

    res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.revoked_api_key}"},
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid or expired API key"


@pytest.mark.asyncio
async def test_auth_expired_key(async_client: AsyncClient):
    """Expired keys must immediately fail authentication."""
    fixture = await create_security_tenant_fixture(async_client, "auth3")

    res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.expired_api_key}"},
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid or expired API key"


@pytest.mark.asyncio
async def test_auth_disabled_tenant_and_project(
    async_client: AsyncClient, db_session: AsyncSession
):
    """Keys belonging to suspended or disabled tenants/projects must be denied."""
    fixture = await create_security_tenant_fixture(async_client, "auth4")

    # 1. Disable Project
    await db_session.execute(
        update(Project).where(Project.id == fixture.project_id).values(status="disabled")
    )
    await db_session.commit()

    res_proj = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert res_proj.status_code == 401
    assert res_proj.json()["detail"] == "Invalid or expired API key"

    # Re-enable project, disable tenant
    await db_session.execute(
        update(Project).where(Project.id == fixture.project_id).values(status="active")
    )
    await db_session.execute(
        update(Tenant).where(Tenant.id == fixture.tenant_id).values(status="suspended")
    )
    await db_session.commit()

    res_tenant = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert res_tenant.status_code == 401
    assert res_tenant.json()["detail"] == "Invalid or expired API key"


@pytest.mark.asyncio
async def test_auth_rotated_key(async_client: AsyncClient):
    """Rotating an API key revokes the old key and activates the new key."""
    fixture = await create_security_tenant_fixture(async_client, "auth5")

    # Create key to rotate
    k_res = await async_client.post(
        f"/api/v1/projects/{fixture.project_id}/api-keys",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={"name": "Key To Rotate", "user_id": str(fixture.owner_user_id)},
    )
    assert k_res.status_code == 201
    old_key = k_res.json()["key"]
    key_id = k_res.json()["id"]

    # Rotate key
    rot_res = await async_client.post(
        f"/api/v1/api-keys/{key_id}/rotate",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
    )
    assert rot_res.status_code == 200
    new_key = rot_res.json()["key"]
    assert new_key != old_key

    # Old key fails
    res_old = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {old_key}"},
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert res_old.status_code == 401

    # New key succeeds
    res_new = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {new_key}"},
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert res_new.status_code == 200


@pytest.mark.asyncio
async def test_auth_no_hash_or_credential_leakage(async_client: AsyncClient):
    """Verify that listing or creating keys NEVER returns the key hash or raw secret on list."""
    fixture = await create_security_tenant_fixture(async_client, "auth6")

    # List keys
    list_res = await async_client.get(
        f"/api/v1/projects/{fixture.project_id}/api-keys",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
    )
    assert list_res.status_code == 200
    keys = list_res.json()
    assert len(keys) > 0
    for k in keys:
        assert "key_hash" not in k
        assert "key" not in k
        assert "password" not in k
        assert "key_prefix" in k
