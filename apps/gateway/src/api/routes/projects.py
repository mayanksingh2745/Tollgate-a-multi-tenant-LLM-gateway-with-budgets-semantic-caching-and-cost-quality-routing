from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.dependencies import get_optional_api_key
from gateway.src.auth.permissions import verify_role_permissions
from gateway.src.db import get_db
from gateway.src.schemas.project import ProjectCreate, ProjectResponse
from gateway.src.services.project_service import (
    create_project,
    get_project,
    list_projects,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/projects", tags=["Projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Project",
)
async def create_project_endpoint(
    tenant_id: UUID,
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    ctx: Optional[AuthenticatedContext] = Depends(get_optional_api_key),
):
    """Create a new project under the tenant."""
    if ctx:
        if ctx.tenant_id != tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
        verify_role_permissions(ctx, ["owner", "admin"])

    return await create_project(db, tenant_id, data)


@router.get("", response_model=List[ProjectResponse], summary="List Tenant Projects")
async def list_projects_endpoint(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: Optional[AuthenticatedContext] = Depends(get_optional_api_key),
):
    """List all projects belonging to the specified tenant."""
    if ctx and ctx.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    return await list_projects(db, tenant_id)


@router.get("/{project_id}", response_model=ProjectResponse, summary="Get Project Details")
async def get_project_endpoint(
    tenant_id: UUID,
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: Optional[AuthenticatedContext] = Depends(get_optional_api_key),
):
    """Retrieve details for a specific project under the tenant."""
    if ctx and ctx.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    return await get_project(db, tenant_id, project_id)
