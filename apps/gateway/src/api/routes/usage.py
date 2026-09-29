import base64
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.dependencies import get_current_api_key
from gateway.src.db import get_db
from gateway.src.schemas.usage import (
    PaginatedUsageResponse,
    UsageDailyRollupResponse,
    UsageEventResponse,
    UsageMonthlyRollupResponse,
)
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import UsageDailyRollup, UsageEvent, UsageMonthlyRollup

router = APIRouter(tags=["Usage & Cost Accounting"])


def encode_cursor(created_at: datetime, item_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{item_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor_str: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        ts_str, id_str = raw.split("|", 1)
        return datetime.fromisoformat(ts_str), UUID(id_str)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination cursor format.",
        ) from None


@router.get(
    "/api/v1/usage",
    response_model=PaginatedUsageResponse,
    summary="Query Usage Events",
)
@router.get(
    "/usage",
    response_model=PaginatedUsageResponse,
    include_in_schema=False,
)
async def query_usage_events(
    tenant_id: Optional[UUID] = Query(None, description="Tenant filter (must match caller)"),
    project_id: Optional[UUID] = Query(None, description="Project filter"),
    start_date: Optional[datetime] = Query(None, description="Start date filter (inclusive)"),
    end_date: Optional[datetime] = Query(None, description="End date filter (inclusive)"),
    provider: Optional[str] = Query(None, description="Provider filter"),
    model: Optional[str] = Query(None, description="Model filter"),
    request_status: Optional[str] = Query(None, alias="status", description="Status filter"),
    limit: int = Query(default=50, ge=1, le=100, description="Max items to return (1-100)"),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    """
    Paginated query for individual usage events.
    Strictly isolated to caller's tenant and project scope.
    """
    # 1. Enforce Tenant Isolation
    if tenant_id and tenant_id != ctx.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot query usage for a different tenant.",
        )

    # 2. Enforce Project Scope
    if ctx.project_id:
        if project_id and project_id != ctx.project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: API key is scoped to a different project.",
            )
        effective_project_id = ctx.project_id
    else:
        effective_project_id = project_id

    # 3. Build Filters
    conditions = [UsageEvent.tenant_id == ctx.tenant_id]

    if effective_project_id:
        conditions.append(UsageEvent.project_id == effective_project_id)
    if start_date:
        conditions.append(UsageEvent.created_at >= start_date)
    if end_date:
        conditions.append(UsageEvent.created_at <= end_date)
    if provider:
        conditions.append(UsageEvent.provider == provider)
    if model:
        conditions.append(UsageEvent.model == model)
    if request_status:
        conditions.append(UsageEvent.status == request_status)

    # 4. Cursor Pagination Filter
    if cursor:
        cursor_created_at, cursor_id = decode_cursor(cursor)
        conditions.append(
            or_(
                UsageEvent.created_at < cursor_created_at,
                and_(
                    UsageEvent.created_at == cursor_created_at,
                    UsageEvent.id < cursor_id,
                ),
            )
        )

    query = (
        select(UsageEvent)
        .where(and_(*conditions))
        .order_by(UsageEvent.created_at.desc(), UsageEvent.id.desc())
        .limit(limit + 1)
    )

    result = await db.execute(query)
    rows = list(result.scalars().all())

    has_more = len(rows) > limit
    items = rows[:limit]

    next_cursor = None
    if has_more and items:
        last_item = items[-1]
        next_cursor = encode_cursor(last_item.created_at, last_item.id)

    return PaginatedUsageResponse(
        items=[UsageEventResponse.model_validate(item) for item in items],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/api/v1/usage/rollups/daily",
    response_model=List[UsageDailyRollupResponse],
    summary="Get Daily Usage Rollups",
)
@router.get(
    "/usage/rollups/daily",
    response_model=List[UsageDailyRollupResponse],
    include_in_schema=False,
)
async def get_daily_rollups(
    project_id: Optional[UUID] = Query(None, description="Project filter"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    provider: Optional[str] = Query(None, description="Provider filter"),
    model: Optional[str] = Query(None, description="Model filter"),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    """
    Returns aggregated daily usage rollups strictly isolated to caller's tenant.
    """
    conditions = [UsageDailyRollup.tenant_id == ctx.tenant_id]

    if ctx.project_id:
        conditions.append(UsageDailyRollup.project_id == ctx.project_id)
    elif project_id:
        conditions.append(UsageDailyRollup.project_id == project_id)

    if start_date:
        conditions.append(UsageDailyRollup.date >= start_date)
    if end_date:
        conditions.append(UsageDailyRollup.date <= end_date)
    if provider:
        conditions.append(UsageDailyRollup.provider == provider)
    if model:
        conditions.append(UsageDailyRollup.model == model)

    stmt = (
        select(UsageDailyRollup)
        .where(and_(*conditions))
        .order_by(UsageDailyRollup.date.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    records = result.scalars().all()
    return [UsageDailyRollupResponse.model_validate(r) for r in records]


@router.get(
    "/api/v1/usage/rollups/monthly",
    response_model=List[UsageMonthlyRollupResponse],
    summary="Get Monthly Usage Rollups",
)
@router.get(
    "/usage/rollups/monthly",
    response_model=List[UsageMonthlyRollupResponse],
    include_in_schema=False,
)
async def get_monthly_rollups(
    project_id: Optional[UUID] = Query(None, description="Project filter"),
    start_month: Optional[str] = Query(None, description="Start month (YYYY-MM)"),
    end_month: Optional[str] = Query(None, description="End month (YYYY-MM)"),
    provider: Optional[str] = Query(None, description="Provider filter"),
    model: Optional[str] = Query(None, description="Model filter"),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    ctx: AuthenticatedContext = Depends(get_current_api_key),
):
    """
    Returns aggregated monthly usage rollups strictly isolated to caller's tenant.
    """
    conditions = [UsageMonthlyRollup.tenant_id == ctx.tenant_id]

    if ctx.project_id:
        conditions.append(UsageMonthlyRollup.project_id == ctx.project_id)
    elif project_id:
        conditions.append(UsageMonthlyRollup.project_id == project_id)

    if start_month:
        conditions.append(UsageMonthlyRollup.month >= start_month)
    if end_month:
        conditions.append(UsageMonthlyRollup.month <= end_month)
    if provider:
        conditions.append(UsageMonthlyRollup.provider == provider)
    if model:
        conditions.append(UsageMonthlyRollup.model == model)

    stmt = (
        select(UsageMonthlyRollup)
        .where(and_(*conditions))
        .order_by(UsageMonthlyRollup.month.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    records = result.scalars().all()
    return [UsageMonthlyRollupResponse.model_validate(r) for r in records]
