import pytest
from fastapi import HTTPException
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.permissions import verify_role_permissions
from httpx import AsyncClient


def test_rbac_hierarchy():
    owner_ctx = AuthenticatedContext(tenant_id="00000000-0000-0000-0000-000000000000", role="owner")
    admin_ctx = AuthenticatedContext(tenant_id="00000000-0000-0000-0000-000000000000", role="admin")
    viewer_ctx = AuthenticatedContext(
        tenant_id="00000000-0000-0000-0000-000000000000", role="viewer"
    )

    # Owner can access owner, admin, viewer endpoints
    verify_role_permissions(owner_ctx, ["owner"])
    verify_role_permissions(owner_ctx, ["admin"])
    verify_role_permissions(owner_ctx, ["viewer"])

    # Admin can access admin & viewer endpoints, but not owner-exclusive
    verify_role_permissions(admin_ctx, ["admin"])
    verify_role_permissions(admin_ctx, ["viewer"])
    with pytest.raises(HTTPException) as exc:
        verify_role_permissions(admin_ctx, ["owner"])
    assert exc.value.status_code == 403

    # Viewer can access viewer endpoints, but not admin or owner
    verify_role_permissions(viewer_ctx, ["viewer"])
    with pytest.raises(HTTPException) as exc:
        verify_role_permissions(viewer_ctx, ["admin"])
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_user_creation_and_roles(async_client: AsyncClient):
    t_res = await async_client.post("/api/v1/tenants", json={"name": "Org", "slug": "org"})
    tenant_id = t_res.json()["id"]

    # Create Owner user
    u1 = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "name": "Alice Owner",
            "email": "ALICE@EXAMPLE.COM",
            "password": "SecretPassword123!",
            "role": "owner",
        },
    )
    assert u1.status_code == 201
    assert u1.json()["email"] == "alice@example.com"  # Normalized lowercase!
    assert u1.json()["role"] == "owner"

    # Create Viewer user
    u2 = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "name": "Bob Viewer",
            "email": "bob@example.com",
            "password": "SecretPassword123!",
            "role": "viewer",
        },
    )
    assert u2.status_code == 201
    assert u2.json()["role"] == "viewer"

    # List users
    list_res = await async_client.get(f"/api/v1/tenants/{tenant_id}/users")
    assert list_res.status_code == 200
    assert len(list_res.json()) == 2
