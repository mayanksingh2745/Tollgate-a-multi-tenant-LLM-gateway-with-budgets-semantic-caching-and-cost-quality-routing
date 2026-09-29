from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.dependencies import get_current_api_key
from gateway.src.auth.permissions import verify_role_permissions
from gateway.src.db import get_db
from gateway.src.schemas.user import UserCreate, UserResponse
from gateway.src.services.user_service import create_user, list_users

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/users", tags=["Users"])


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="Create User in Tenant")
async def create_user_endpoint(
    tenant_id: UUID,
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    ctx: Optional[AuthenticatedContext] = Depends(get_current_api_key)
):
    """Create a user within the specified tenant with RBAC & tenant isolation."""
    if ctx:
        if ctx.tenant_id != tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
        verify_role_permissions(ctx, ["owner", "admin"])

    return await create_user(db, tenant_id, data)


@router.get("", response_model=List[UserResponse], summary="List Users in Tenant")
async def list_users_endpoint(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: Optional[AuthenticatedContext] = Depends(get_current_api_key)
):
    """List all users belonging to the specified tenant."""
    if ctx and ctx.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    return await list_users(db, tenant_id)
