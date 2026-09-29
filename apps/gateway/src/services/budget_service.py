import time
from typing import Dict, Optional, Tuple
from uuid import UUID

from gateway.src.budgets.manager import BudgetLimits
from gateway.src.schemas.budget import BudgetConfigResponse, BudgetConfigUpdate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import Project, Tenant

# In-memory short-lived cache for effective budget limits: (tenant_id, project_id) -> (cached_at, BudgetLimits)
_limits_cache: Dict[Tuple[UUID, Optional[UUID]], Tuple[float, BudgetLimits]] = {}


def invalidate_budget_cache(tenant_id: UUID, project_id: Optional[UUID] = None) -> None:
    keys_to_del = [
        k for k in _limits_cache if k[0] == tenant_id and (project_id is None or k[1] == project_id)
    ]
    for k in keys_to_del:
        _limits_cache.pop(k, None)


async def get_effective_budget_limits(
    db: AsyncSession, tenant_id: UUID, project_id: Optional[UUID] = None
) -> BudgetLimits:
    cache_key = (tenant_id, project_id)
    now = time.time()
    if cache_key in _limits_cache:
        cached_at, cached_limits = _limits_cache[cache_key]
        if now - cached_at < 60.0:  # 60s TTL
            return cached_limits

    tenant_query = select(Tenant).where(Tenant.id == tenant_id)
    tenant_res = await db.execute(tenant_query)
    tenant = tenant_res.scalars().first()

    project = None
    if project_id:
        proj_query = select(Project).where(Project.id == project_id)
        proj_res = await db.execute(proj_query)
        project = proj_res.scalars().first()

    limits = BudgetLimits(
        tenant_daily_limit=tenant.daily_budget_microdollars if tenant else None,
        tenant_monthly_limit=tenant.monthly_budget_microdollars if tenant else None,
        project_daily_limit=project.daily_budget_microdollars if project else None,
        project_monthly_limit=project.monthly_budget_microdollars if project else None,
    )
    _limits_cache[cache_key] = (now, limits)
    return limits


async def get_tenant_budget(db: AsyncSession, tenant_id: UUID) -> Optional[BudgetConfigResponse]:
    query = select(Tenant).where(Tenant.id == tenant_id)
    result = await db.execute(query)
    tenant = result.scalars().first()
    if not tenant:
        return None
    return BudgetConfigResponse(
        daily_budget_microdollars=tenant.daily_budget_microdollars,
        monthly_budget_microdollars=tenant.monthly_budget_microdollars,
        currency="USD",
    )


async def update_tenant_budget(
    db: AsyncSession, tenant_id: UUID, data: BudgetConfigUpdate
) -> Optional[BudgetConfigResponse]:
    query = select(Tenant).where(Tenant.id == tenant_id)
    result = await db.execute(query)
    tenant = result.scalars().first()
    if not tenant:
        return None

    tenant.daily_budget_microdollars = data.daily_budget_microdollars
    tenant.monthly_budget_microdollars = data.monthly_budget_microdollars
    await db.commit()
    await db.refresh(tenant)

    invalidate_budget_cache(tenant_id)

    return BudgetConfigResponse(
        daily_budget_microdollars=tenant.daily_budget_microdollars,
        monthly_budget_microdollars=tenant.monthly_budget_microdollars,
        currency="USD",
    )


async def get_project_budget(
    db: AsyncSession, project_id: UUID, tenant_id: Optional[UUID] = None
) -> Optional[BudgetConfigResponse]:
    query = select(Project).where(Project.id == project_id)
    if tenant_id:
        query = query.where(Project.tenant_id == tenant_id)
    result = await db.execute(query)
    project = result.scalars().first()
    if not project:
        return None
    return BudgetConfigResponse(
        daily_budget_microdollars=project.daily_budget_microdollars,
        monthly_budget_microdollars=project.monthly_budget_microdollars,
        currency="USD",
    )


async def update_project_budget(
    db: AsyncSession, project_id: UUID, data: BudgetConfigUpdate, tenant_id: Optional[UUID] = None
) -> Optional[BudgetConfigResponse]:
    query = select(Project).where(Project.id == project_id)
    if tenant_id:
        query = query.where(Project.tenant_id == tenant_id)
    result = await db.execute(query)
    project = result.scalars().first()
    if not project:
        return None

    project.daily_budget_microdollars = data.daily_budget_microdollars
    project.monthly_budget_microdollars = data.monthly_budget_microdollars
    await db.commit()
    await db.refresh(project)

    invalidate_budget_cache(project.tenant_id, project_id)

    return BudgetConfigResponse(
        daily_budget_microdollars=project.daily_budget_microdollars,
        monthly_budget_microdollars=project.monthly_budget_microdollars,
        currency="USD",
    )
