import pytest
from fastapi import HTTPException
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.permissions import verify_role_permissions
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


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


@pytest.mark.asyncio
async def test_api_key_role_resolution_and_rbac_propagation(
    async_client: AsyncClient, db_session: AsyncSession
):
    """
    Verify owner, admin, viewer, and unassociated API keys:
    - user_id is properly persisted and returned
    - role is correctly resolved from user.role
    - unassociated keys default to role="admin"
    - viewer keys cannot perform owner/admin mutations (403)
    - admin/owner keys can perform mutations (200/201)
    """
    from gateway.src.services.api_key_service import verify_and_authenticate_key

    # 1. Setup Tenant and Project
    t_res = await async_client.post(
        "/api/v1/tenants", json={"name": "RBAC Corp", "slug": "rbac-corp"}
    )
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects", json={"name": "RBAC Project", "slug": "rbac-proj"}
    )
    project_id = p_res.json()["id"]

    # 2. Create Owner User and Owner Key
    u_owner = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "name": "Owner User",
            "email": "owner@corp.com",
            "password": "Password123!",
            "role": "owner",
        },
    )
    owner_user_id = u_owner.json()["id"]

    k_owner = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        json={"name": "Owner Key", "user_id": owner_user_id},
    )
    assert k_owner.status_code == 201
    assert k_owner.json()["user_id"] == owner_user_id
    owner_raw_key = k_owner.json()["key"]

    # 3. Create Admin User and Admin Key
    u_admin = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "name": "Admin User",
            "email": "admin@corp.com",
            "password": "Password123!",
            "role": "admin",
        },
    )
    admin_user_id = u_admin.json()["id"]

    k_admin = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        json={"name": "Admin Key", "user_id": admin_user_id},
    )
    assert k_admin.status_code == 201
    assert k_admin.json()["user_id"] == admin_user_id
    admin_raw_key = k_admin.json()["key"]

    # 4. Create Viewer User and Viewer Key
    u_viewer = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "name": "Viewer User",
            "email": "viewer@corp.com",
            "password": "Password123!",
            "role": "viewer",
        },
    )
    viewer_user_id = u_viewer.json()["id"]

    k_viewer = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        json={"name": "Viewer Key", "user_id": viewer_user_id},
    )
    assert k_viewer.status_code == 201
    assert k_viewer.json()["user_id"] == viewer_user_id
    viewer_raw_key = k_viewer.json()["key"]

    # 5. Create Unassociated (Service) Key
    k_unassoc = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        json={"name": "Service Key"},
    )
    assert k_unassoc.status_code == 201
    assert k_unassoc.json()["user_id"] is None
    unassoc_raw_key = k_unassoc.json()["key"]

    # 6. Verify authentication resolutions directly
    res_owner = await verify_and_authenticate_key(db_session, owner_raw_key)
    assert res_owner is not None
    _, _, _, owner_u = res_owner
    assert owner_u is not None and owner_u.role == "owner"

    res_admin = await verify_and_authenticate_key(db_session, admin_raw_key)
    assert res_admin is not None
    _, _, _, admin_u = res_admin
    assert admin_u is not None and admin_u.role == "admin"

    res_viewer = await verify_and_authenticate_key(db_session, viewer_raw_key)
    assert res_viewer is not None
    _, _, _, viewer_u = res_viewer
    assert viewer_u is not None and viewer_u.role == "viewer"

    res_unassoc = await verify_and_authenticate_key(db_session, unassoc_raw_key)
    assert res_unassoc is not None
    _, _, _, unassoc_u = res_unassoc
    assert unassoc_u is None  # Project-level key without user

    # 7. Test HTTP authorization via headers
    viewer_headers = {"Authorization": f"Bearer {viewer_raw_key}"}
    admin_headers = {"Authorization": f"Bearer {admin_raw_key}"}
    owner_headers = {"Authorization": f"Bearer {owner_raw_key}"}
    unassoc_headers = {"Authorization": f"Bearer {unassoc_raw_key}"}

    # Viewer CANNOT invalidate cache -> 403
    r_del_viewer = await async_client.delete(
        f"/api/v1/projects/{project_id}/cache", headers=viewer_headers
    )
    assert r_del_viewer.status_code == 403

    # Viewer CANNOT create API keys -> 403
    r_key_viewer = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        headers=viewer_headers,
        json={"name": "Forbidden Key"},
    )
    assert r_key_viewer.status_code == 403

    # Admin CAN invalidate cache -> 200
    r_del_admin = await async_client.delete(
        f"/api/v1/projects/{project_id}/cache", headers=admin_headers
    )
    assert r_del_admin.status_code == 200

    # Owner CAN invalidate cache -> 200
    r_del_owner = await async_client.delete(
        f"/api/v1/projects/{project_id}/cache", headers=owner_headers
    )
    assert r_del_owner.status_code == 200

    # Unassociated key defaults to admin role -> CAN invalidate cache -> 200
    r_del_unassoc = await async_client.delete(
        f"/api/v1/projects/{project_id}/cache", headers=unassoc_headers
    )
    assert r_del_unassoc.status_code == 200


@pytest.mark.asyncio
async def test_api_key_user_tenant_isolation_and_suspension(
    async_client: AsyncClient, db_session: AsyncSession
):
    """
    Verify:
    - Cannot create API key with user_id belonging to another tenant (404)
    - Cannot create API key for inactive user (400)
    - If user is suspended, existing API key fails authentication (401)
    """
    from tollgate_core.models import User

    # 1. Setup Tenant A and Project A
    t_a = await async_client.post("/api/v1/tenants", json={"name": "Tenant A", "slug": "tenant-a"})
    tenant_a_id = t_a.json()["id"]
    p_a = await async_client.post(
        f"/api/v1/tenants/{tenant_a_id}/projects", json={"name": "Project A", "slug": "proj-a"}
    )
    proj_a_id = p_a.json()["id"]

    # 2. Setup Tenant B and User B
    t_b = await async_client.post("/api/v1/tenants", json={"name": "Tenant B", "slug": "tenant-b"})
    tenant_b_id = t_b.json()["id"]
    u_b = await async_client.post(
        f"/api/v1/tenants/{tenant_b_id}/users",
        json={
            "name": "User B",
            "email": "userb@tb.com",
            "password": "Password123!",
            "role": "admin",
        },
    )
    user_b_id = u_b.json()["id"]

    # 3. Attempt to create API key in Tenant A with User B from Tenant B -> 404
    cross_res = await async_client.post(
        f"/api/v1/projects/{proj_a_id}/api-keys",
        json={"name": "Cross Key", "user_id": user_b_id},
    )
    assert cross_res.status_code == 404

    # 4. Create user in Tenant A
    u_a = await async_client.post(
        f"/api/v1/tenants/{tenant_a_id}/users",
        json={
            "name": "User A",
            "email": "usera@ta.com",
            "password": "Password123!",
            "role": "admin",
        },
    )
    user_a_id = u_a.json()["id"]

    # Create active key for User A
    k_a = await async_client.post(
        f"/api/v1/projects/{proj_a_id}/api-keys",
        json={"name": "User A Key", "user_id": user_a_id},
    )
    assert k_a.status_code == 201
    raw_key = k_a.json()["key"]

    # Works initially
    res_ok = await async_client.get(
        f"/api/v1/tenants/{tenant_a_id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert res_ok.status_code == 200

    # 5. Suspend User A in DB
    from uuid import UUID

    user_obj = await db_session.get(User, UUID(user_a_id))
    user_obj.status = "suspended"
    await db_session.commit()

    # Attempt to authenticate with suspended user's key -> 401
    res_suspended = await async_client.get(
        f"/api/v1/tenants/{tenant_a_id}",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert res_suspended.status_code == 401
    assert res_suspended.json()["detail"] == "Invalid or expired API key"

    # Attempt to create new API key for suspended user -> 400
    res_create_suspended = await async_client.post(
        f"/api/v1/projects/{proj_a_id}/api-keys",
        json={"name": "Suspended Key", "user_id": user_a_id},
    )
    assert res_create_suspended.status_code == 400
