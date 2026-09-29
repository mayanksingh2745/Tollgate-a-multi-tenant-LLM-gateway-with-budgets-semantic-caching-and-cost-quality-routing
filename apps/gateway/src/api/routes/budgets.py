from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.dependencies import get_current_api_key
from gateway.src.auth.permissions import verify_role_permissions
from gateway.src.db import get_db
from gateway.src.schemas.budget import BudgetConfigResponse, BudgetConfigUpdate
from gateway.src.services.budget_service import (
    get_project_budget,
    get_tenant_budget,
    update_project_budget,
    update_tenant_budget,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1", tags=["Budgets"])


@router.get(
    "/tenants/{tenant_id}/budget",
    response_model=BudgetConfigResponse,
    summary="Get Tenant Budget",
)
async def get_tenant_budget_endpoint(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    if ctx.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    res = await get_tenant_budget(db, tenant_id)
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    return res


@router.put(
    "/tenants/{tenant_id}/budget",
    response_model=BudgetConfigResponse,
    summary="Update Tenant Budget",
)
async def update_tenant_budget_endpoint(
    tenant_id: UUID,
    data: BudgetConfigUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    if ctx.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    verify_role_permissions(ctx, ["owner", "admin"])

    res = await update_tenant_budget(db, tenant_id, data)
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    return res


@router.get(
    "/projects/{project_id}/budget",
    response_model=BudgetConfigResponse,
    summary="Get Project Budget",
)
async def get_project_budget_endpoint(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    res = await get_project_budget(db, project_id, tenant_id=ctx.tenant_id)
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return res


@router.put(
    "/projects/{project_id}/budget",
    response_model=BudgetConfigResponse,
    summary="Update Project Budget",
)
async def update_project_budget_endpoint(
    project_id: UUID,
    data: BudgetConfigUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    verify_role_permissions(ctx, ["owner", "admin"])
    res = await update_project_budget(db, project_id, data, tenant_id=ctx.tenant_id)
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return res


@router.get(
    "/tenants/{tenant_id}/projects/{project_id}/budget",
    response_model=BudgetConfigResponse,
    summary="Get Project Budget (Nested)",
)
async def get_nested_project_budget_endpoint(
    tenant_id: UUID,
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    if ctx.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    return await get_project_budget_endpoint(project_id, db, ctx)


@router.put(
    "/tenants/{tenant_id}/projects/{project_id}/budget",
    response_model=BudgetConfigResponse,
    summary="Update Project Budget (Nested)",
)
async def update_nested_project_budget_endpoint(
    tenant_id: UUID,
    project_id: UUID,
    data: BudgetConfigUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    if ctx.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    return await update_project_budget_endpoint(project_id, data, db, ctx)
