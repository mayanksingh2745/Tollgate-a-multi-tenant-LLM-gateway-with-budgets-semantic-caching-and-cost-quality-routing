from dataclasses import dataclass
from typing import Dict
from uuid import UUID

from httpx import AsyncClient


@dataclass
class TenantFixtureData:
    tenant_id: UUID
    tenant_slug: str
    project_id: UUID
    owner_user_id: UUID
    owner_api_key: str
    admin_user_id: UUID
    admin_api_key: str
    viewer_user_id: UUID
    viewer_api_key: str
    revoked_api_key: str
    expired_api_key: str
    raw_keys: Dict[str, str]


async def create_security_tenant_fixture(
    client: AsyncClient, slug_prefix: str = "sec"
) -> TenantFixtureData:
    # 1. Create Tenant
    t_res = await client.post(
        "/api/v1/tenants",
        json={"name": f"Security Tenant {slug_prefix}", "slug": f"{slug_prefix}-tenant"},
    )
    assert t_res.status_code == 201, t_res.text
    tenant_id = UUID(t_res.json()["id"])

    # 2. Create Project
    p_res = await client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": f"Project {slug_prefix}", "slug": f"{slug_prefix}-proj"},
    )
    assert p_res.status_code == 201, p_res.text
    project_id = UUID(p_res.json()["id"])

    # 3. Create Users (Owner, Admin, Viewer)
    u_owner = await client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "name": f"Owner {slug_prefix}",
            "email": f"owner-{slug_prefix}@example.com",
            "password": "SecurePassword123!",
            "role": "owner",
        },
    )
    assert u_owner.status_code == 201
    owner_id = UUID(u_owner.json()["id"])

    u_admin = await client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "name": f"Admin {slug_prefix}",
            "email": f"admin-{slug_prefix}@example.com",
            "password": "SecurePassword123!",
            "role": "admin",
        },
    )
    assert u_admin.status_code == 201
    admin_id = UUID(u_admin.json()["id"])

    u_viewer = await client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "name": f"Viewer {slug_prefix}",
            "email": f"viewer-{slug_prefix}@example.com",
            "password": "SecurePassword123!",
            "role": "viewer",
        },
    )
    assert u_viewer.status_code == 201
    viewer_id = UUID(u_viewer.json()["id"])

    # 4. Create API Keys for each user
    k_owner = await client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        json={"name": "Owner Key", "user_id": str(owner_id)},
    )
    assert k_owner.status_code == 201
    owner_key = k_owner.json()["key"]

    k_admin = await client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        json={"name": "Admin Key", "user_id": str(admin_id)},
    )
    assert k_admin.status_code == 201
    admin_key = k_admin.json()["key"]

    k_viewer = await client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        json={"name": "Viewer Key", "user_id": str(viewer_id)},
    )
    assert k_viewer.status_code == 201
    viewer_key = k_viewer.json()["key"]

    # 5. Create a key to revoke
    k_rev = await client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        json={"name": "Revocable Key", "user_id": str(admin_id)},
    )
    assert k_rev.status_code == 201
    rev_key_id = k_rev.json()["id"]
    rev_key = k_rev.json()["key"]

    # Revoke it
    del_res = await client.delete(
        f"/api/v1/api-keys/{rev_key_id}",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert del_res.status_code == 200

    # 6. Create an expired key
    k_exp = await client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        json={
            "name": "Expired Key",
            "user_id": str(admin_id),
            "expires_at": "2020-01-01T00:00:00Z",
        },
    )
    assert k_exp.status_code == 201
    exp_key = k_exp.json()["key"]

    return TenantFixtureData(
        tenant_id=tenant_id,
        tenant_slug=f"{slug_prefix}-tenant",
        project_id=project_id,
        owner_user_id=owner_id,
        owner_api_key=owner_key,
        admin_user_id=admin_id,
        admin_api_key=admin_key,
        viewer_user_id=viewer_id,
        viewer_api_key=viewer_key,
        revoked_api_key=rev_key,
        expired_api_key=exp_key,
        raw_keys={
            "owner": owner_key,
            "admin": admin_key,
            "viewer": viewer_key,
            "revoked": rev_key,
            "expired": exp_key,
        },
    )
