import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import UsageDailyRollup, UsageEvent, UsageMonthlyRollup
from tollgate_core.usage import UsageEventPayload
from tollgate_core.usage_metrics import usage_metrics

logger = logging.getLogger("tollgate.worker.persistence")


async def persist_usage_event(session: AsyncSession, event: UsageEventPayload) -> bool:
    """
    Atomically persists a usage event and updates corresponding daily and monthly rollups.
    Enforces idempotency at the database level:
    If event_id already exists in usage_events, the event is safely ignored,
    rollups are NOT updated, and the function returns False.
    Returns True if the event was inserted and rollups updated.
    """
    bind = session.bind
    is_postgres = False
    if bind and hasattr(bind, "dialect"):
        is_postgres = "postgres" in bind.dialect.name

    if is_postgres:
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert

    # 1. Insert UsageEvent with ON CONFLICT (event_id) DO NOTHING
    event_stmt = (
        dialect_insert(UsageEvent)
        .values(
            id=uuid.uuid4(),
            event_id=event.event_id,
            event_version=event.event_version,
            request_id=event.request_id,
            reservation_id=event.reservation_id,
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            api_key_id=event.api_key_id,
            provider=event.provider,
            model=event.model,
            stream=event.stream,
            status=event.status,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            total_tokens=event.total_tokens,
            estimated_cost=event.estimated_cost,
            actual_cost=event.actual_cost,
            latency_ms=event.latency_ms,
            attempt_count=event.attempt_count,
            fallback_used=event.fallback_used,
            created_at=event.timestamp,
            processed_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(UsageEvent.id)
    )

    result = await session.execute(event_stmt)
    inserted_id = result.scalar_one_or_none()

    if inserted_id is None:
        # Event already exists! Duplicate event safely skipped.
        usage_metrics.increment("usage_event_duplicate_total")
        logger.info(
            f"Duplicate usage event detected and idempotently skipped: "
            f"event_id={event.event_id} request_id={event.request_id}"
        )
        return False

    # 2. Update Daily Rollup
    date_str = event.timestamp.strftime("%Y-%m-%d")
    is_success = 1 if event.status == "success" else 0
    is_failure = 1 if event.status != "success" else 0
    now_utc = datetime.now(timezone.utc)

    daily_stmt = (
        dialect_insert(UsageDailyRollup)
        .values(
            id=uuid.uuid4(),
            date=date_str,
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            provider=event.provider,
            model=event.model,
            request_count=1,
            success_count=is_success,
            failure_count=is_failure,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            total_tokens=event.total_tokens,
            estimated_cost=event.estimated_cost,
            actual_cost=event.actual_cost,
            updated_at=now_utc,
        )
        .on_conflict_do_update(
            index_elements=["date", "tenant_id", "project_id", "provider", "model"],
            set_={
                "request_count": UsageDailyRollup.request_count + 1,
                "success_count": UsageDailyRollup.success_count + is_success,
                "failure_count": UsageDailyRollup.failure_count + is_failure,
                "input_tokens": UsageDailyRollup.input_tokens + event.input_tokens,
                "output_tokens": UsageDailyRollup.output_tokens + event.output_tokens,
                "total_tokens": UsageDailyRollup.total_tokens + event.total_tokens,
                "estimated_cost": UsageDailyRollup.estimated_cost + event.estimated_cost,
                "actual_cost": UsageDailyRollup.actual_cost + event.actual_cost,
                "updated_at": now_utc,
            },
        )
    )
    await session.execute(daily_stmt)

    # 3. Update Monthly Rollup
    month_str = event.timestamp.strftime("%Y-%m")
    monthly_stmt = (
        dialect_insert(UsageMonthlyRollup)
        .values(
            id=uuid.uuid4(),
            month=month_str,
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            provider=event.provider,
            model=event.model,
            request_count=1,
            success_count=is_success,
            failure_count=is_failure,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            total_tokens=event.total_tokens,
            estimated_cost=event.estimated_cost,
            actual_cost=event.actual_cost,
            updated_at=now_utc,
        )
        .on_conflict_do_update(
            index_elements=["month", "tenant_id", "project_id", "provider", "model"],
            set_={
                "request_count": UsageMonthlyRollup.request_count + 1,
                "success_count": UsageMonthlyRollup.success_count + is_success,
                "failure_count": UsageMonthlyRollup.failure_count + is_failure,
                "input_tokens": UsageMonthlyRollup.input_tokens + event.input_tokens,
                "output_tokens": UsageMonthlyRollup.output_tokens + event.output_tokens,
                "total_tokens": UsageMonthlyRollup.total_tokens + event.total_tokens,
                "estimated_cost": UsageMonthlyRollup.estimated_cost + event.estimated_cost,
                "actual_cost": UsageMonthlyRollup.actual_cost + event.actual_cost,
                "updated_at": now_utc,
            },
        )
    )
    await session.execute(monthly_stmt)

    logger.debug(
        f"Persisted usage event and rollups: event_id={event.event_id} request_id={event.request_id} "
        f"tenant_id={event.tenant_id} date={date_str} month={month_str}"
    )
    return True
