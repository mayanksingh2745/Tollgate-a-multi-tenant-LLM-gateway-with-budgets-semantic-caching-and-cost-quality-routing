"""Tenant-isolated analytics queries and aggregation service for Tollgate Dashboard."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from gateway.src.cache import cache_metrics, exact_cache
from gateway.src.cache.semantic import semantic_cache_metrics
from gateway.src.schemas.dashboard import (
    BudgetsOverviewResponse,
    BudgetStatus,
    CacheAnalyticsResponse,
    CostAnalyticsResponse,
    CostBreakdownItem,
    ModelAnalyticsItem,
    OverviewResponse,
    PaginatedRequestsResponse,
    ProjectBudgetStatus,
    ProviderAnalyticsItem,
    RequestDetailResponse,
    RequestSummaryItem,
    RouterAnalyticsResponse,
    TimeRange,
    UsagePoint,
    UsageSeriesResponse,
)
from sqlalchemy import (
    and_,
    asc,
    case,
    desc,
    distinct,
    func,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import Project, SemanticCacheEntry, Tenant, UsageEvent

logger = logging.getLogger("tollgate.dashboard_service")


def resolve_time_range(
    range_str: Optional[str] = "24h",
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> Tuple[datetime, datetime]:
    """Resolves start and end datetimes in UTC based on range preset or custom dates."""
    now = datetime.now(timezone.utc)
    if range_str == "custom" and start_time and end_time:
        return start_time, end_time

    if range_str == "7d":
        return now - timedelta(days=7), now
    elif range_str == "30d":
        return now - timedelta(days=30), now
    else:  # default "24h"
        return now - timedelta(hours=24), now


class DashboardService:
    @staticmethod
    async def get_overview(
        db: AsyncSession,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        range_str: str = "24h",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> OverviewResponse:
        start_dt, end_dt = resolve_time_range(range_str, start_time, end_time)

        conditions = [
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.created_at >= start_dt,
            UsageEvent.created_at <= end_dt,
        ]
        if project_id:
            conditions.append(UsageEvent.project_id == project_id)

        stmt = select(
            func.count(UsageEvent.id).label("total_requests"),
            func.coalesce(func.sum(UsageEvent.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageEvent.estimated_cost), 0).label("estimated_cost"),
            func.coalesce(func.sum(UsageEvent.actual_cost), 0).label("actual_cost"),
            func.count(case((UsageEvent.status != "success", 1))).label("failures"),
            func.count(case((UsageEvent.router_route == "cheap", 1))).label("cheap_routes"),
            func.count(case((UsageEvent.router_route == "strong", 1))).label("strong_routes"),
            func.count(distinct(UsageEvent.model)).label("active_models"),
            func.count(distinct(UsageEvent.provider)).label("active_providers"),
        ).where(and_(*conditions))

        res = await db.execute(stmt)
        row = res.one()

        total_requests = int(row.total_requests or 0)
        total_tokens = int(row.total_tokens or 0)
        input_tokens = int(row.input_tokens or 0)
        output_tokens = int(row.output_tokens or 0)
        est_cost = int(row.estimated_cost or 0)
        act_cost = int(row.actual_cost or 0)
        failures = int(row.failures or 0)
        cheap_routes = int(row.cheap_routes or 0)
        strong_routes = int(row.strong_routes or 0)
        active_models = int(row.active_models or 0)
        active_providers = int(row.active_providers or 0)

        # Cache metrics (tenant-isolated)
        exact_hits = await exact_cache.get_tenant_hits(tenant_id, project_id)
        # Semantic cache hits from database
        sem_stmt = select(func.coalesce(func.sum(SemanticCacheEntry.hit_count), 0)).where(
            SemanticCacheEntry.tenant_id == tenant_id
        )
        if project_id:
            sem_stmt = sem_stmt.where(SemanticCacheEntry.project_id == project_id)
        sem_res = await db.execute(sem_stmt)
        semantic_hits = int(sem_res.scalar() or 0)

        cache_hits = exact_hits + semantic_hits
        total_ops = total_requests + cache_hits
        cache_hit_rate = (cache_hits / total_ops) if total_ops > 0 else 0.0
        error_rate = (failures / total_requests) if total_requests > 0 else 0.0

        routed_total = cheap_routes + strong_routes
        cheap_pct = (cheap_routes / routed_total * 100.0) if routed_total > 0 else 0.0
        strong_pct = (strong_routes / routed_total * 100.0) if routed_total > 0 else 0.0

        return OverviewResponse(
            period=TimeRange(start=start_dt, end=end_dt),
            total_requests=total_requests,
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_microdollars=est_cost,
            actual_cost_microdollars=act_cost,
            estimated_cost_usd=round(est_cost / 1_000_000, 4),
            actual_cost_usd=round(act_cost / 1_000_000, 4),
            provider_failures=failures,
            error_rate=round(error_rate, 4),
            cache_hits=cache_hits,
            cache_hit_rate=round(cache_hit_rate, 4),
            exact_cache_hits=exact_hits,
            semantic_cache_hits=semantic_hits,
            cheap_routing_percentage=round(cheap_pct, 1),
            strong_routing_percentage=round(strong_pct, 1),
            active_models_count=active_models,
            active_providers_count=active_providers,
        )

    @staticmethod
    async def get_usage_timeseries(
        db: AsyncSession,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        range_str: str = "24h",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        interval: Optional[str] = None,
    ) -> UsageSeriesResponse:
        start_dt, end_dt = resolve_time_range(range_str, start_time, end_time)

        # Decide interval if not explicit
        if not interval:
            duration = (end_dt - start_dt).total_seconds()
            interval = "hour" if duration <= 86400 * 2 else "day"

        bind = db.bind
        is_postgres = False
        if bind and hasattr(bind, "dialect"):
            is_postgres = "postgres" in bind.dialect.name

        if is_postgres:
            trunc_unit = "hour" if interval == "hour" else "day"
            time_expr = func.to_char(
                func.date_trunc(trunc_unit, UsageEvent.created_at),
                "YYYY-MM-DD HH24:00" if interval == "hour" else "YYYY-MM-DD",
            )
        else:
            time_format = "%Y-%m-%d %H:00" if interval == "hour" else "%Y-%m-%d"
            time_expr = func.strftime(time_format, UsageEvent.created_at)

        conditions = [
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.created_at >= start_dt,
            UsageEvent.created_at <= end_dt,
        ]
        if project_id:
            conditions.append(UsageEvent.project_id == project_id)

        stmt = (
            select(
                time_expr.label("bucket"),
                func.count(UsageEvent.id).label("requests"),
                func.coalesce(func.sum(UsageEvent.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(UsageEvent.actual_cost), 0).label("cost"),
                func.count(case((UsageEvent.status == "success", 1))).label("success_count"),
                func.count(case((UsageEvent.status != "success", 1))).label("failure_count"),
            )
            .where(and_(*conditions))
            .group_by("bucket")
            .order_by(asc("bucket"))
        )

        res = await db.execute(stmt)
        rows = res.all()

        points = [
            UsagePoint(
                timestamp=str(r.bucket),
                requests=int(r.requests or 0),
                tokens=int(r.tokens or 0),
                input_tokens=int(r.input_tokens or 0),
                output_tokens=int(r.output_tokens or 0),
                cost_microdollars=int(r.cost or 0),
                cost_usd=round(int(r.cost or 0) / 1_000_000, 4),
                success_count=int(r.success_count or 0),
                failure_count=int(r.failure_count or 0),
            )
            for r in rows
        ]

        return UsageSeriesResponse(interval=interval, points=points)

    @staticmethod
    async def get_costs(
        db: AsyncSession,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        range_str: str = "24h",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> CostAnalyticsResponse:
        start_dt, end_dt = resolve_time_range(range_str, start_time, end_time)

        conditions = [
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.created_at >= start_dt,
            UsageEvent.created_at <= end_dt,
        ]
        if project_id:
            conditions.append(UsageEvent.project_id == project_id)

        # 1. Total and input/output costs
        tot_stmt = select(
            func.coalesce(func.sum(UsageEvent.actual_cost), 0).label("tot_cost"),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("tot_in"),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("tot_out"),
        ).where(and_(*conditions))
        tot_res = await db.execute(tot_stmt)
        tot_row = tot_res.one()
        tot_cost = int(tot_row.tot_cost or 0)
        tot_in = int(tot_row.tot_in or 0)
        tot_out = int(tot_row.tot_out or 0)

        # Conservative proportional split of input vs output cost
        tot_tok = tot_in + tot_out
        in_cost = int(tot_cost * (tot_in / tot_tok)) if tot_tok > 0 else 0
        out_cost = tot_cost - in_cost

        # 2. Cost by Model
        model_stmt = (
            select(
                UsageEvent.model.label("name"),
                func.coalesce(func.sum(UsageEvent.actual_cost), 0).label("cost"),
                func.count(UsageEvent.id).label("requests"),
                func.coalesce(func.sum(UsageEvent.total_tokens), 0).label("tokens"),
            )
            .where(and_(*conditions))
            .group_by(UsageEvent.model)
            .order_by(desc("cost"))
        )
        m_rows = (await db.execute(model_stmt)).all()
        by_model = [
            CostBreakdownItem(
                name=r.name,
                cost_microdollars=int(r.cost),
                cost_usd=round(int(r.cost) / 1_000_000, 4),
                percentage=round((int(r.cost) / tot_cost * 100.0) if tot_cost > 0 else 0.0, 1),
                request_count=int(r.requests),
                total_tokens=int(r.tokens),
            )
            for r in m_rows
        ]

        # 3. Cost by Provider
        prov_stmt = (
            select(
                UsageEvent.provider.label("name"),
                func.coalesce(func.sum(UsageEvent.actual_cost), 0).label("cost"),
                func.count(UsageEvent.id).label("requests"),
                func.coalesce(func.sum(UsageEvent.total_tokens), 0).label("tokens"),
            )
            .where(and_(*conditions))
            .group_by(UsageEvent.provider)
            .order_by(desc("cost"))
        )
        p_rows = (await db.execute(prov_stmt)).all()
        by_provider = [
            CostBreakdownItem(
                name=r.name,
                cost_microdollars=int(r.cost),
                cost_usd=round(int(r.cost) / 1_000_000, 4),
                percentage=round((int(r.cost) / tot_cost * 100.0) if tot_cost > 0 else 0.0, 1),
                request_count=int(r.requests),
                total_tokens=int(r.tokens),
            )
            for r in p_rows
        ]

        # 4. Cost by Project
        proj_stmt = (
            select(
                Project.name.label("name"),
                func.coalesce(func.sum(UsageEvent.actual_cost), 0).label("cost"),
                func.count(UsageEvent.id).label("requests"),
                func.coalesce(func.sum(UsageEvent.total_tokens), 0).label("tokens"),
            )
            .join(Project, Project.id == UsageEvent.project_id)
            .where(and_(*conditions))
            .group_by(Project.id, Project.name)
            .order_by(desc("cost"))
        )
        pr_rows = (await db.execute(proj_stmt)).all()
        by_project = [
            CostBreakdownItem(
                name=r.name,
                cost_microdollars=int(r.cost),
                cost_usd=round(int(r.cost) / 1_000_000, 4),
                percentage=round((int(r.cost) / tot_cost * 100.0) if tot_cost > 0 else 0.0, 1),
                request_count=int(r.requests),
                total_tokens=int(r.tokens),
            )
            for r in pr_rows
        ]

        return CostAnalyticsResponse(
            total_cost_microdollars=tot_cost,
            total_cost_usd=round(tot_cost / 1_000_000, 4),
            input_cost_microdollars=in_cost,
            output_cost_microdollars=out_cost,
            by_model=by_model,
            by_provider=by_provider,
            by_project=by_project,
        )

    @staticmethod
    async def get_budgets(
        db: AsyncSession,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
    ) -> BudgetsOverviewResponse:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # 1. Fetch Tenant
        t_stmt = select(Tenant).where(Tenant.id == tenant_id)
        tenant = (await db.execute(t_stmt)).scalar_one_or_none()

        # Monthly & Daily Tenant Spending
        m_spend_stmt = select(func.coalesce(func.sum(UsageEvent.actual_cost), 0)).where(
            UsageEvent.tenant_id == tenant_id, UsageEvent.created_at >= month_start
        )
        d_spend_stmt = select(func.coalesce(func.sum(UsageEvent.actual_cost), 0)).where(
            UsageEvent.tenant_id == tenant_id, UsageEvent.created_at >= day_start
        )
        m_spent = int((await db.execute(m_spend_stmt)).scalar() or 0)
        d_spent = int((await db.execute(d_spend_stmt)).scalar() or 0)

        t_mb = tenant.monthly_budget_microdollars if tenant else None
        t_db = tenant.daily_budget_microdollars if tenant else None

        m_util = round((m_spent / t_mb) if t_mb and t_mb > 0 else 0.0, 4)
        d_util = round((d_spent / t_db) if t_db and t_db > 0 else 0.0, 4)

        tenant_budget = BudgetStatus(
            monthly_budget_microdollars=t_mb,
            daily_budget_microdollars=t_db,
            monthly_spent_microdollars=m_spent,
            daily_spent_microdollars=d_spent,
            monthly_utilization=m_util,
            daily_utilization=d_util,
            monthly_remaining_microdollars=(max(0, t_mb - m_spent) if t_mb else None),
            daily_remaining_microdollars=(max(0, t_db - d_spent) if t_db else None),
        )

        # 2. Fetch Projects
        p_conditions = [Project.tenant_id == tenant_id]
        if project_id:
            p_conditions.append(Project.id == project_id)

        proj_stmt = select(Project).where(and_(*p_conditions)).order_by(Project.name.asc())
        projects = (await db.execute(proj_stmt)).scalars().all()

        project_budgets: List[ProjectBudgetStatus] = []
        for p in projects:
            pm_stmt = select(func.coalesce(func.sum(UsageEvent.actual_cost), 0)).where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.project_id == p.id,
                UsageEvent.created_at >= month_start,
            )
            pd_stmt = select(func.coalesce(func.sum(UsageEvent.actual_cost), 0)).where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.project_id == p.id,
                UsageEvent.created_at >= day_start,
            )
            pm_spent = int((await db.execute(pm_stmt)).scalar() or 0)
            pd_spent = int((await db.execute(pd_stmt)).scalar() or 0)

            p_mb = p.monthly_budget_microdollars
            p_db = p.daily_budget_microdollars

            pm_util = round((pm_spent / p_mb) if p_mb and p_mb > 0 else 0.0, 4)
            pd_util = round((pd_spent / p_db) if p_db and p_db > 0 else 0.0, 4)

            project_budgets.append(
                ProjectBudgetStatus(
                    project_id=p.id,
                    project_name=p.name,
                    monthly_budget_microdollars=p_mb,
                    daily_budget_microdollars=p_db,
                    monthly_spent_microdollars=pm_spent,
                    daily_spent_microdollars=pd_spent,
                    monthly_utilization=pm_util,
                    daily_utilization=pd_util,
                    monthly_remaining_microdollars=(max(0, p_mb - pm_spent) if p_mb else None),
                )
            )

        return BudgetsOverviewResponse(tenant_budget=tenant_budget, projects=project_budgets)

    @staticmethod
    async def get_models(
        db: AsyncSession,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        range_str: str = "24h",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[ModelAnalyticsItem]:
        start_dt, end_dt = resolve_time_range(range_str, start_time, end_time)

        conditions = [
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.created_at >= start_dt,
            UsageEvent.created_at <= end_dt,
        ]
        if project_id:
            conditions.append(UsageEvent.project_id == project_id)

        stmt = (
            select(
                UsageEvent.model,
                func.count(UsageEvent.id).label("requests"),
                func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(UsageEvent.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(UsageEvent.actual_cost), 0).label("cost"),
                func.coalesce(func.avg(UsageEvent.latency_ms), 0.0).label("avg_latency"),
                func.count(case((UsageEvent.status != "success", 1))).label("failures"),
            )
            .where(and_(*conditions))
            .group_by(UsageEvent.model)
            .order_by(desc("requests"))
        )

        rows = (await db.execute(stmt)).all()
        return [
            ModelAnalyticsItem(
                model=r.model,
                requests=int(r.requests),
                input_tokens=int(r.input_tokens),
                output_tokens=int(r.output_tokens),
                total_tokens=int(r.total_tokens),
                cost_microdollars=int(r.cost),
                cost_usd=round(int(r.cost) / 1_000_000, 4),
                avg_latency_ms=round(float(r.avg_latency), 2),
                error_rate=round(
                    int(r.failures) / int(r.requests) if int(r.requests) > 0 else 0.0, 4
                ),
            )
            for r in rows
        ]

    @staticmethod
    async def get_providers(
        db: AsyncSession,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        range_str: str = "24h",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[ProviderAnalyticsItem]:
        start_dt, end_dt = resolve_time_range(range_str, start_time, end_time)

        conditions = [
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.created_at >= start_dt,
            UsageEvent.created_at <= end_dt,
        ]
        if project_id:
            conditions.append(UsageEvent.project_id == project_id)

        stmt = (
            select(
                UsageEvent.provider,
                func.count(UsageEvent.id).label("requests"),
                func.count(case((UsageEvent.status != "success", 1))).label("failures"),
                func.coalesce(
                    func.sum(
                        case((UsageEvent.attempt_count > 1, UsageEvent.attempt_count - 1), else_=0)
                    ),
                    0,
                ).label("retries"),
                func.count(case((UsageEvent.fallback_used.is_(True), 1))).label("fallbacks"),
                func.coalesce(func.avg(UsageEvent.latency_ms), 0.0).label("avg_latency"),
            )
            .where(and_(*conditions))
            .group_by(UsageEvent.provider)
            .order_by(desc("requests"))
        )

        rows = (await db.execute(stmt)).all()
        return [
            ProviderAnalyticsItem(
                provider=r.provider,
                requests=int(r.requests),
                failures=int(r.failures),
                retries=int(r.retries),
                fallbacks=int(r.fallbacks),
                avg_latency_ms=round(float(r.avg_latency), 2),
                error_rate=round(
                    int(r.failures) / int(r.requests) if int(r.requests) > 0 else 0.0, 4
                ),
                fallback_rate=round(
                    int(r.fallbacks) / int(r.requests) if int(r.requests) > 0 else 0.0, 4
                ),
            )
            for r in rows
        ]

    @staticmethod
    async def get_cache_analytics(
        db: AsyncSession,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
    ) -> CacheAnalyticsResponse:
        exact_hits = await exact_cache.get_tenant_hits(tenant_id, project_id)
        exact_misses = await exact_cache.get_tenant_misses(tenant_id, project_id)
        exact_ops = exact_hits + exact_misses
        exact_hit_rate = (exact_hits / exact_ops) if exact_ops > 0 else 0.0

        # Semantic cache hits and entries
        sem_stmt = select(
            func.coalesce(func.sum(SemanticCacheEntry.hit_count), 0).label("hits"),
            func.count(SemanticCacheEntry.id).label("count"),
        ).where(SemanticCacheEntry.tenant_id == tenant_id)
        if project_id:
            sem_stmt = sem_stmt.where(SemanticCacheEntry.project_id == project_id)

        sem_res = await db.execute(sem_stmt)
        sem_row = sem_res.one()
        semantic_hits = int(sem_row.hits or 0)
        semantic_entries_count = int(sem_row.count or 0)

        # Semantic misses from metrics
        stats = semantic_cache_metrics.get_stats()
        counters = stats.get("counters", {})
        semantic_misses = counters.get("semantic_cache_misses_total", 0)
        sem_ops = semantic_hits + semantic_misses
        sem_hit_rate = (semantic_hits / sem_ops) if sem_ops > 0 else 0.0

        total_hits = exact_hits + semantic_hits
        total_misses = exact_misses + semantic_misses
        overall_ops = total_hits + total_misses
        overall_hit_rate = (total_hits / overall_ops) if overall_ops > 0 else 0.0

        # Estimated cost avoided: compute average cost of live requests for tenant
        avg_cost_stmt = select(func.coalesce(func.avg(UsageEvent.actual_cost), 0)).where(
            UsageEvent.tenant_id == tenant_id, UsageEvent.status == "success"
        )
        avg_cost = int(
            (await db.execute(avg_cost_stmt)).scalar() or 500
        )  # default 500 microdollars
        est_cost_avoided = total_hits * avg_cost

        cache_stat = cache_metrics.get_all()
        return CacheAnalyticsResponse(
            exact_hits=exact_hits,
            exact_misses=exact_misses,
            exact_hit_rate=round(exact_hit_rate, 4),
            semantic_hits=semantic_hits,
            semantic_misses=semantic_misses,
            semantic_hit_rate=round(sem_hit_rate, 4),
            overall_hit_rate=round(overall_hit_rate, 4),
            total_cache_hits=total_hits,
            estimated_calls_avoided=total_hits,
            estimated_cost_avoided_microdollars=est_cost_avoided,
            estimated_cost_avoided_usd=round(est_cost_avoided / 1_000_000, 4),
            cache_lookup_errors=cache_stat.get("cache_lookup_errors_total", 0),
            cache_write_errors=cache_stat.get("cache_write_errors_total", 0),
            semantic_cache_errors=counters.get("semantic_cache_errors_total", 0),
            semantic_entries_count=semantic_entries_count,
        )

    @staticmethod
    async def get_router_analytics(
        db: AsyncSession,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        range_str: str = "24h",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> RouterAnalyticsResponse:
        start_dt, end_dt = resolve_time_range(range_str, start_time, end_time)

        conditions = [
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.created_at >= start_dt,
            UsageEvent.created_at <= end_dt,
        ]
        if project_id:
            conditions.append(UsageEvent.project_id == project_id)

        stmt = select(
            func.count(case((UsageEvent.router_route == "cheap", 1))).label("cheap"),
            func.count(case((UsageEvent.router_route == "strong", 1))).label("strong"),
            func.count(case((UsageEvent.router_route == "passthrough", 1))).label("passthrough"),
            func.count(case((UsageEvent.router_fallback.is_(True), 1))).label("fallbacks"),
            func.count(case((UsageEvent.status != "success", 1))).label("errors"),
            func.coalesce(func.avg(UsageEvent.router_confidence), 0.0).label("avg_conf"),
            func.count(
                case(
                    (
                        and_(
                            UsageEvent.router_route == "cheap",
                            UsageEvent.fallback_used.is_(True),
                        ),
                        1,
                    )
                )
            ).label("cheap_to_strong_provider"),
        ).where(and_(*conditions))

        row = (await db.execute(stmt)).one()

        cheap = int(row.cheap or 0)
        strong = int(row.strong or 0)
        passthrough = int(row.passthrough or 0)
        fallbacks = int(row.fallbacks or 0)
        errors = int(row.errors or 0)
        avg_conf = float(row.avg_conf or 0.0)
        cheap_to_strong = int(row.cheap_to_strong_provider or 0)

        tot_routed = cheap + strong
        cheap_pct = (cheap / tot_routed * 100.0) if tot_routed > 0 else 0.0
        strong_pct = (strong / tot_routed * 100.0) if tot_routed > 0 else 0.0

        # Load offline evaluation report if present
        offline_eval: Optional[Dict[str, Any]] = None
        eval_path = (
            Path(__file__).resolve().parents[4] / "evaluation" / "router" / "evaluation_report.json"
        )
        if eval_path.exists():
            try:
                with open(eval_path, "r", encoding="utf-8") as f:
                    offline_eval = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load offline evaluation report: {e}")

        from gateway.src.config import settings

        return RouterAnalyticsResponse(
            router_mode=settings.router_mode if settings.router_enabled else "disabled",
            cheap_selections=cheap,
            strong_selections=strong,
            passthrough_selections=passthrough,
            fallbacks=fallbacks,
            errors=errors,
            cheap_percentage=round(cheap_pct, 1),
            strong_percentage=round(strong_pct, 1),
            avg_confidence=round(avg_conf, 4),
            router_cheap_provider_strong=cheap_to_strong,
            offline_evaluation=offline_eval,
        )

    @staticmethod
    async def get_requests(
        db: AsyncSession,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        page: int = 1,
        page_size: int = 25,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        status: Optional[str] = None,
        router_route: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> PaginatedRequestsResponse:
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        offset = (page - 1) * page_size

        conditions = [UsageEvent.tenant_id == tenant_id]
        if project_id:
            conditions.append(UsageEvent.project_id == project_id)
        if start_time:
            conditions.append(UsageEvent.created_at >= start_time)
        if end_time:
            conditions.append(UsageEvent.created_at <= end_time)
        if model:
            conditions.append(UsageEvent.model == model)
        if provider:
            conditions.append(UsageEvent.provider == provider)
        if status:
            conditions.append(UsageEvent.status == status)
        if router_route:
            conditions.append(UsageEvent.router_route == router_route)
        if search:
            search_pattern = f"%{search.strip()}%"
            conditions.append(
                or_(
                    UsageEvent.request_id.ilike(search_pattern),
                    UsageEvent.model.ilike(search_pattern),
                    UsageEvent.provider.ilike(search_pattern),
                )
            )

        # Count total matches
        count_stmt = select(func.count(UsageEvent.id)).where(and_(*conditions))
        total = int((await db.execute(count_stmt)).scalar() or 0)

        # Safe sorting whitelist
        sortable_columns = {
            "created_at": UsageEvent.created_at,
            "actual_cost": UsageEvent.actual_cost,
            "latency_ms": UsageEvent.latency_ms,
            "total_tokens": UsageEvent.total_tokens,
        }
        order_col = sortable_columns.get(sort_by, UsageEvent.created_at)
        order_func = asc(order_col) if sort_order.lower() == "asc" else desc(order_col)

        stmt = (
            select(
                UsageEvent.request_id,
                UsageEvent.created_at,
                UsageEvent.project_id,
                Project.name.label("project_name"),
                UsageEvent.model,
                UsageEvent.provider,
                UsageEvent.status,
                UsageEvent.latency_ms,
                UsageEvent.total_tokens,
                UsageEvent.actual_cost,
                UsageEvent.router_route,
                UsageEvent.cache_status,
            )
            .join(Project, Project.id == UsageEvent.project_id)
            .where(and_(*conditions))
            .order_by(order_func)
            .offset(offset)
            .limit(page_size)
        )

        rows = (await db.execute(stmt)).all()
        items = [
            RequestSummaryItem(
                request_id=r.request_id,
                created_at=r.created_at,
                project_id=r.project_id,
                project_name=r.project_name,
                model=r.model,
                provider=r.provider,
                status=r.status,
                latency_ms=round(r.latency_ms, 2),
                total_tokens=r.total_tokens,
                actual_cost_microdollars=r.actual_cost,
                actual_cost_usd=round(r.actual_cost / 1_000_000, 4),
                router_route=r.router_route,
                cache_status=r.cache_status,
            )
            for r in rows
        ]

        total_pages = (total + page_size - 1) // page_size if total > 0 else 1
        return PaginatedRequestsResponse(
            items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
        )

    @staticmethod
    async def get_request_detail(
        db: AsyncSession,
        tenant_id: UUID,
        request_id: str,
    ) -> Optional[RequestDetailResponse]:
        stmt = (
            select(
                UsageEvent,
                Project.name.label("project_name"),
            )
            .join(Project, Project.id == UsageEvent.project_id)
            .where(UsageEvent.tenant_id == tenant_id, UsageEvent.request_id == request_id)
        )
        res = await db.execute(stmt)
        row = res.first()
        if not row:
            return None

        event, project_name = row
        return RequestDetailResponse(
            request_id=event.request_id,
            event_id=event.event_id,
            created_at=event.created_at,
            processed_at=event.processed_at,
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            project_name=project_name,
            provider=event.provider,
            model=event.model,
            original_model=event.original_model,
            stream=event.stream,
            status=event.status,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            total_tokens=event.total_tokens,
            estimated_cost_microdollars=event.estimated_cost,
            actual_cost_microdollars=event.actual_cost,
            latency_ms=round(event.latency_ms, 2),
            attempt_count=event.attempt_count,
            fallback_used=event.fallback_used,
            router_mode=event.router_mode,
            router_route=event.router_route,
            router_confidence=event.router_confidence,
            router_model_version=event.router_model_version,
            router_fallback=bool(event.router_fallback),
            cache_status=event.cache_status,
        )
