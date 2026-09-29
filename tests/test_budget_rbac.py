from uuid import uuid4

import pytest
from fastapi import HTTPException
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.permissions import verify_role_permissions


def test_budget_rbac_permissions():
    tenant_id = uuid4()
    owner_ctx = AuthenticatedContext(tenant_id=tenant_id, role="owner")
    admin_ctx = AuthenticatedContext(tenant_id=tenant_id, role="admin")
    viewer_ctx = AuthenticatedContext(tenant_id=tenant_id, role="viewer")

    # Owners and Admins are permitted to update budgets
    verify_role_permissions(owner_ctx, ["owner", "admin"])
    verify_role_permissions(admin_ctx, ["owner", "admin"])

    # Viewers are forbidden from modifying budgets
    with pytest.raises(HTTPException) as exc_info:
        verify_role_permissions(viewer_ctx, ["owner", "admin"])
    assert exc_info.value.status_code == 403
    assert "Insufficient permissions" in exc_info.value.detail
