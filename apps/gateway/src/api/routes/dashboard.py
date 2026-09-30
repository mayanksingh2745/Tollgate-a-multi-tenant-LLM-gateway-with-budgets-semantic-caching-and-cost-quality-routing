"""Tollgate Tenant Analytics & Management Dashboard API endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.dependencies import get_current_api_key
from gateway.src.auth.permissions import verify_role_permissions
from gateway.src.db import get_db
from gateway.src.schemas.dashboard import (
    BudgetsOverviewResponse,
    CacheAnalyticsResponse,
    CostAnalyticsResponse,
    CurrentUserProfile,
    ModelAnalyticsItem,
    OverviewResponse,
    PaginatedRequestsResponse,
    ProviderAnalyticsItem,
    RequestDetailResponse,
    RouterAnalyticsResponse,
    UsageSeriesResponse,
)
from gateway.src.services.dashboard_service import DashboardService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import APIKey, Project, Tenant, User

router = APIRouter(prefix="/api/v1/dashboard", tags=["Tenant Dashboard"])


async def validate_project_scope(
    db: AsyncSession, ctx: AuthenticatedContext, project_id: Optional[UUID]
) -> Optional[UUID]:
    """
    Validates that project_id belongs to the authenticated tenant.
    For owner/admin roles, caller has access to all projects in the tenant.
    If project_id is None, returns None (meaning 'all projects in tenant').
    If caller is a project-scoped viewer, enforces project restriction.
    """
    if project_id:
        proj = await db.scalar(
            select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id)
        )
        if not proj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found or not in tenant.",
            )
        if ctx.role == "viewer" and ctx.project_id and ctx.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Restricted to assigned project.",
            )
        return project_id

    if ctx.role == "viewer" and ctx.project_id:
        return ctx.project_id

    return None


@router.get("/me", response_model=CurrentUserProfile, summary="Get Current Dashboard User")
async def get_dashboard_me(
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    """Returns the current user/key profile, role, tenant information, and accessible projects."""
    tenant = await db.scalar(select(Tenant).where(Tenant.id == ctx.tenant_id))
    user = await db.scalar(select(User).where(User.id == ctx.user_id)) if ctx.user_id else None

    # Fetch projects
    p_stmt = select(Project).where(Project.tenant_id == ctx.tenant_id).order_by(Project.name.asc())
    if ctx.project_id:
        p_stmt = p_stmt.where(Project.id == ctx.project_id)
    projects = (await db.execute(p_stmt)).scalars().all()

    return CurrentUserProfile(
        user_id=ctx.user_id,
        email=user.email if user else None,
        name=user.name if user else "API Key User",
        role=ctx.role,
        tenant_id=ctx.tenant_id,
        tenant_name=tenant.name if tenant else "Default Tenant",
        project_id=ctx.project_id,
        projects=[{"id": p.id, "name": p.name, "slug": p.slug} for p in projects],
    )


@router.get("/overview", response_model=OverviewResponse, summary="Get Dashboard Overview")
async def get_overview_endpoint(
    range: str = Query("24h", description="Time range: 24h, 7d, 30d, custom"),
    start_time: Optional[datetime] = Query(None, description="Custom start UTC time"),
    end_time: Optional[datetime] = Query(None, description="Custom end UTC time"),
    project_id: Optional[UUID] = Query(None, description="Project filter"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    verify_role_permissions(ctx, ["owner", "admin", "viewer"])
    eff_proj_id = await validate_project_scope(db, ctx, project_id)
    return await DashboardService.get_overview(
        db, ctx.tenant_id, eff_proj_id, range, start_time, end_time
    )


@router.get("/usage", response_model=UsageSeriesResponse, summary="Get Usage Time-Series")
async def get_usage_endpoint(
    range: str = Query("24h", description="Time range: 24h, 7d, 30d, custom"),
    interval: Optional[str] = Query(None, description="Interval: hour, day"),
    start_time: Optional[datetime] = Query(None, description="Custom start UTC time"),
    end_time: Optional[datetime] = Query(None, description="Custom end UTC time"),
    project_id: Optional[UUID] = Query(None, description="Project filter"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    verify_role_permissions(ctx, ["owner", "admin", "viewer"])
    eff_proj_id = await validate_project_scope(db, ctx, project_id)
    return await DashboardService.get_usage_timeseries(
        db, ctx.tenant_id, eff_proj_id, range, start_time, end_time, interval
    )


@router.get("/costs", response_model=CostAnalyticsResponse, summary="Get Cost Breakdown")
async def get_costs_endpoint(
    range: str = Query("24h", description="Time range: 24h, 7d, 30d, custom"),
    start_time: Optional[datetime] = Query(None, description="Custom start UTC time"),
    end_time: Optional[datetime] = Query(None, description="Custom end UTC time"),
    project_id: Optional[UUID] = Query(None, description="Project filter"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    verify_role_permissions(ctx, ["owner", "admin", "viewer"])
    eff_proj_id = await validate_project_scope(db, ctx, project_id)
    return await DashboardService.get_costs(
        db, ctx.tenant_id, eff_proj_id, range, start_time, end_time
    )


@router.get("/budgets", response_model=BudgetsOverviewResponse, summary="Get Budgets Status")
async def get_budgets_endpoint(
    project_id: Optional[UUID] = Query(None, description="Project filter"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    verify_role_permissions(ctx, ["owner", "admin", "viewer"])
    eff_proj_id = await validate_project_scope(db, ctx, project_id)
    return await DashboardService.get_budgets(db, ctx.tenant_id, eff_proj_id)


@router.get("/models", response_model=List[ModelAnalyticsItem], summary="Get Model Analytics")
async def get_models_endpoint(
    range: str = Query("24h", description="Time range: 24h, 7d, 30d, custom"),
    start_time: Optional[datetime] = Query(None, description="Custom start UTC time"),
    end_time: Optional[datetime] = Query(None, description="Custom end UTC time"),
    project_id: Optional[UUID] = Query(None, description="Project filter"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    verify_role_permissions(ctx, ["owner", "admin", "viewer"])
    eff_proj_id = await validate_project_scope(db, ctx, project_id)
    return await DashboardService.get_models(
        db, ctx.tenant_id, eff_proj_id, range, start_time, end_time
    )


@router.get(
    "/providers", response_model=List[ProviderAnalyticsItem], summary="Get Provider Analytics"
)
async def get_providers_endpoint(
    range: str = Query("24h", description="Time range: 24h, 7d, 30d, custom"),
    start_time: Optional[datetime] = Query(None, description="Custom start UTC time"),
    end_time: Optional[datetime] = Query(None, description="Custom end UTC time"),
    project_id: Optional[UUID] = Query(None, description="Project filter"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    verify_role_permissions(ctx, ["owner", "admin", "viewer"])
    eff_proj_id = await validate_project_scope(db, ctx, project_id)
    return await DashboardService.get_providers(
        db, ctx.tenant_id, eff_proj_id, range, start_time, end_time
    )


@router.get("/cache", response_model=CacheAnalyticsResponse, summary="Get Cache Analytics")
async def get_cache_endpoint(
    project_id: Optional[UUID] = Query(None, description="Project filter"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    verify_role_permissions(ctx, ["owner", "admin", "viewer"])
    eff_proj_id = await validate_project_scope(db, ctx, project_id)
    return await DashboardService.get_cache_analytics(db, ctx.tenant_id, eff_proj_id)


@router.get("/router", response_model=RouterAnalyticsResponse, summary="Get Router Analytics")
async def get_router_endpoint(
    range: str = Query("24h", description="Time range: 24h, 7d, 30d, custom"),
    start_time: Optional[datetime] = Query(None, description="Custom start UTC time"),
    end_time: Optional[datetime] = Query(None, description="Custom end UTC time"),
    project_id: Optional[UUID] = Query(None, description="Project filter"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    verify_role_permissions(ctx, ["owner", "admin", "viewer"])
    eff_proj_id = await validate_project_scope(db, ctx, project_id)
    return await DashboardService.get_router_analytics(
        db, ctx.tenant_id, eff_proj_id, range, start_time, end_time
    )


@router.get("/requests", response_model=PaginatedRequestsResponse, summary="List Requests")
async def get_requests_endpoint(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page"),
    project_id: Optional[UUID] = Query(None, description="Project filter"),
    start_time: Optional[datetime] = Query(None, description="Start UTC time"),
    end_time: Optional[datetime] = Query(None, description="End UTC time"),
    model: Optional[str] = Query(None, description="Model filter"),
    provider: Optional[str] = Query(None, description="Provider filter"),
    status: Optional[str] = Query(None, description="Status filter"),
    router_route: Optional[str] = Query(None, description="Router route filter (cheap, strong)"),
    search: Optional[str] = Query(None, description="Search request_id or model"),
    sort_by: str = Query(
        "created_at", description="Sort by field: created_at, actual_cost, latency_ms, total_tokens"
    ),
    sort_order: str = Query("desc", description="Sort order: asc, desc"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    verify_role_permissions(ctx, ["owner", "admin", "viewer"])
    eff_proj_id = await validate_project_scope(db, ctx, project_id)
    return await DashboardService.get_requests(
        db,
        ctx.tenant_id,
        eff_proj_id,
        page,
        page_size,
        start_time,
        end_time,
        model,
        provider,
        status,
        router_route,
        search,
        sort_by,
        sort_order,
    )


@router.get(
    "/requests/{request_id}",
    response_model=RequestDetailResponse,
    summary="Get Request Details",
)
async def get_request_detail_endpoint(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    """Returns safe metadata for a specific request. Never leaks prompts, completions, or keys."""
    verify_role_permissions(ctx, ["owner", "admin", "viewer"])
    detail = await DashboardService.get_request_detail(db, ctx.tenant_id, request_id)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found or access denied.",
        )
    return detail


@router.get("/projects", response_model=List[Dict[str, Any]], summary="List Tenant Projects")
async def list_dashboard_projects(
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    verify_role_permissions(ctx, ["owner", "admin", "viewer"])
    stmt = select(Project).where(Project.tenant_id == ctx.tenant_id).order_by(Project.name.asc())
    if ctx.project_id:
        stmt = stmt.where(Project.id == ctx.project_id)
    projs = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "slug": p.slug,
            "status": p.status,
            "created_at": p.created_at.isoformat(),
            "monthly_budget_microdollars": p.monthly_budget_microdollars,
            "daily_budget_microdollars": p.daily_budget_microdollars,
        }
        for p in projs
    ]


@router.get(
    "/api-keys", response_model=List[Dict[str, Any]], summary="List Tenant API Keys Metadata"
)
async def list_dashboard_api_keys(
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    """Lists API key metadata for current tenant. Strictly omits secret keys."""
    verify_role_permissions(ctx, ["owner", "admin", "viewer"])
    stmt = (
        select(APIKey, Project.name.label("project_name"))
        .join(Project, Project.id == APIKey.project_id)
        .where(APIKey.tenant_id == ctx.tenant_id)
        .order_by(APIKey.created_at.desc())
    )
    if ctx.project_id:
        stmt = stmt.where(APIKey.project_id == ctx.project_id)
    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": k.id,
            "project_id": k.project_id,
            "project_name": p_name,
            "name": k.name,
            "key_prefix": k.key_prefix,
            "status": k.status,
            "created_at": k.created_at.isoformat(),
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
        }
        for k, p_name in rows
    ]
