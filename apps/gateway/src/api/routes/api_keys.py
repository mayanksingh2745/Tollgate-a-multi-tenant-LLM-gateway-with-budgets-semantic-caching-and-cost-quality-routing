from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.dependencies import get_optional_api_key
from gateway.src.auth.permissions import verify_role_permissions
from gateway.src.db import get_db
from gateway.src.schemas.api_key import (
    APIKeyCreate,
    APIKeyCreateResponse,
    APIKeyResponse,
)
from gateway.src.services.api_key_service import (
    create_api_key,
    list_api_keys,
    revoke_api_key,
    rotate_api_key,
)

router = APIRouter(tags=["API Keys"])


@router.post(
    "/api/v1/projects/{project_id}/api-keys",
    response_model=APIKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create API Key"
)
async def create_api_key_endpoint(
    project_id: UUID,
    data: APIKeyCreate,
    db: AsyncSession = Depends(get_db),
    ctx: Optional[AuthenticatedContext] = Depends(get_optional_api_key)
):
    """
    Generates a new API key for the project.
    The complete raw secret key is returned ONLY once in this response!
    """
    if ctx:
        verify_role_permissions(ctx, ["owner", "admin"])
        tenant_id = ctx.tenant_id
    else:
        from sqlalchemy import select
        from tollgate_core.models import Project
        res = await db.execute(select(Project).where(Project.id == project_id))
        proj = res.scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        tenant_id = proj.tenant_id

    return await create_api_key(db, project_id, tenant_id, data)


@router.get(
    "/api/v1/projects/{project_id}/api-keys",
    response_model=List[APIKeyResponse],
    summary="List API Keys"
)
async def list_api_keys_endpoint(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: Optional[AuthenticatedContext] = Depends(get_optional_api_key)
):
    """Lists metadata for all API keys under the project (excludes raw secret keys)."""
    if ctx:
        tenant_id = ctx.tenant_id
    else:
        from sqlalchemy import select
        from tollgate_core.models import Project
        res = await db.execute(select(Project).where(Project.id == project_id))
        proj = res.scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        tenant_id = proj.tenant_id

    return await list_api_keys(db, project_id, tenant_id)


@router.delete(
    "/api/v1/api-keys/{api_key_id}",
    response_model=APIKeyResponse,
    summary="Revoke API Key"
)
async def revoke_api_key_endpoint(
    api_key_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: Optional[AuthenticatedContext] = Depends(get_optional_api_key)
):
    """Revokes an API key, disabling future authentication attempts."""
    if ctx:
        verify_role_permissions(ctx, ["owner", "admin"])
        tenant_id = ctx.tenant_id
    else:
        from sqlalchemy import select
        from tollgate_core.models import APIKey
        res = await db.execute(select(APIKey).where(APIKey.id == api_key_id))
        key_obj = res.scalar_one_or_none()
        if not key_obj:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key not found.")
        tenant_id = key_obj.tenant_id

    return await revoke_api_key(db, api_key_id, tenant_id)


@router.post(
    "/api/v1/api-keys/{api_key_id}/rotate",
    response_model=APIKeyCreateResponse,
    summary="Rotate API Key"
)
async def rotate_api_key_endpoint(
    api_key_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: Optional[AuthenticatedContext] = Depends(get_optional_api_key)
):
    """
    Rotates an API key: immediately revokes the old key and generates a new active key.
    Returns the new raw secret key ONLY once.
    """
    if ctx:
        verify_role_permissions(ctx, ["owner", "admin"])
        tenant_id = ctx.tenant_id
    else:
        from sqlalchemy import select
        from tollgate_core.models import APIKey
        res = await db.execute(select(APIKey).where(APIKey.id == api_key_id))
        key_obj = res.scalar_one_or_none()
        if not key_obj:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key not found.")
        tenant_id = key_obj.tenant_id

    return await rotate_api_key(db, api_key_id, tenant_id)
