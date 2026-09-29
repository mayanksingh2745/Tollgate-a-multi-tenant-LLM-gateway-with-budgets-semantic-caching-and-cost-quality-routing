from typing import Callable, List

from fastapi import HTTPException, status
from gateway.src.auth.context import AuthenticatedContext


def verify_role_permissions(ctx: AuthenticatedContext, allowed_roles: List[str]) -> None:
    role_hierarchy = {
        "owner": ["owner", "admin", "viewer"],
        "admin": ["admin", "viewer"],
        "viewer": ["viewer"],
    }

    user_permitted_roles = role_hierarchy.get(ctx.role, [])

    # Check if any allowed role matches user's permitted scope
    if not any(req_role in user_permitted_roles for req_role in allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this action.",
        )


def require_role(*allowed_roles: str) -> Callable[[AuthenticatedContext], None]:
    def check_permission(ctx: AuthenticatedContext) -> None:
        verify_role_permissions(ctx, list(allowed_roles))

    return check_permission
