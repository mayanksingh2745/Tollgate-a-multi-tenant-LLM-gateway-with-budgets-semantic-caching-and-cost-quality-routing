import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import UsageDailyRollup, UsageEvent
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.consumer import UsageWorkerConsumer
from apps.worker.src.persistence import persist_usage_event


@pytest.mark.asyncio
async def test_multi_worker_consumer_identity_separation():
    """
    Verifies that multiple worker instances instantiate distinct consumer identities
    under the same consumer group and do not interfere with each other's state.
    """
    mock_redis = AsyncMock()
    mock_session_factory = AsyncMock()

    worker_1 = UsageWorkerConsumer(
        redis_client=mock_redis,
        session_factory=mock_session_factory,
        consumer_group="tg-usage-workers",
        consumer_name="worker-alpha",
    )
    worker_2 = UsageWorkerConsumer(
        redis_client=mock_redis,
        session_factory=mock_session_factory,
        consumer_group="tg-usage-workers",
        consumer_name="worker-beta",
    )

    assert worker_1.consumer_group == worker_2.consumer_group == "tg-usage-workers"
    assert worker_1.consumer_name == "worker-alpha"
    assert worker_2.consumer_name == "worker-beta"
    assert worker_1.consumer_name != worker_2.consumer_name


@pytest.mark.asyncio
async def test_worker_crash_and_pending_reclaim(db_session: AsyncSession):
    """
    Simulates a worker crash during stream event processing:
    1. Worker 1 receives message and enters Pending Entries List (PEL).
    2. Worker 1 crashes before database commit and XACK.
    3. Worker 2 detects the message exceeded idle threshold and executes XAUTOCLAIM.
    4. Worker 2 successfully persists the event and sends XACK.
    """
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    event_id = uuid.uuid4()
    request_id = f"req_failover_{uuid.uuid4().hex[:8]}"

    event = UsageEventPayload(
        event_id=event_id,
        event_version="1.0",
        request_id=request_id,
        reservation_id=f"res_{uuid.uuid4().hex[:8]}",
        tenant_id=tenant_id,
        project_id=project_id,
        api_key_id=uuid.uuid4(),
        provider="openai",
        model="gpt-4o",
        stream=False,
        status="success",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        estimated_cost=3000,
        actual_cost=2500,
        latency_ms=120.5,
        attempt_count=1,
        fallback_used=False,
        created_at=datetime.now(timezone.utc),
    )

    message_id = "1711800000000-1"
    raw_message = event.to_stream_entry()

    # Mock Redis client simulating XAUTOCLAIM returning the abandoned message
    mock_redis = AsyncMock()
    mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [(message_id, raw_message)], []))
    mock_redis.xack = AsyncMock(return_value=1)

    # Session factory returning the active test DB session
    class TestSessionFactory:
        def __call__(self):
            return db_session

    worker_2 = UsageWorkerConsumer(
        redis_client=mock_redis,
        session_factory=TestSessionFactory(),
        consumer_group="tg-usage-workers",
        consumer_name="worker-replica-2",
        claim_idle_seconds=1,
    )

    # Worker 2 reclaims and processes the abandoned message
    reclaimed = await worker_2.reclaim_stale_messages()
    assert reclaimed == 1

    # Verify XACK was called with message_id by Worker 2
    mock_redis.xack.assert_called_once_with(worker_2.stream_name, "tg-usage-workers", message_id)

    # Verify event was persisted to PostgreSQL
    stmt = select(UsageEvent).where(UsageEvent.event_id == event_id)
    saved_event = (await db_session.execute(stmt)).scalar_one_or_none()
    assert saved_event is not None
    assert saved_event.request_id == request_id
    assert saved_event.total_tokens == 150
    assert saved_event.actual_cost == 2500


@pytest.mark.asyncio
async def test_idempotency_prevents_double_counting_on_replay(db_session: AsyncSession):
    """
    Tests the critical failure scenario:
    Worker commits to the database, but network crash prevents XACK.
    The message is redelivered / reclaimed by another worker.
    The second attempt MUST NOT double-count tokens or actual_cost in daily/monthly rollups.
    """
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    event_id = uuid.uuid4()

    event = UsageEventPayload(
        event_id=event_id,
        event_version="1.0",
        request_id=f"req_idem_{uuid.uuid4().hex[:8]}",
        reservation_id=f"res_idem_{uuid.uuid4().hex[:8]}",
        tenant_id=tenant_id,
        project_id=project_id,
        api_key_id=uuid.uuid4(),
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        stream=False,
        status="success",
        input_tokens=200,
        output_tokens=100,
        total_tokens=300,
        estimated_cost=6000,
        actual_cost=5000,
        latency_ms=250.0,
        attempt_count=1,
        fallback_used=False,
        created_at=datetime.now(timezone.utc),
    )

    # 1. First execution: Success
    inserted_first = await persist_usage_event(db_session, event)
    await db_session.commit()
    assert inserted_first is True

    # Check rollups after first run
    today_date = datetime.now(timezone.utc).date()
    daily_stmt = select(UsageDailyRollup).where(
        UsageDailyRollup.tenant_id == tenant_id,
        UsageDailyRollup.date == today_date,
    )
    rollup = (await db_session.execute(daily_stmt)).scalar_one()
    assert rollup.total_tokens == 300
    assert rollup.actual_cost == 5000
    assert rollup.request_count == 1

    # 2. Second execution (Replay after simulated ACK network failure)
    inserted_second = await persist_usage_event(db_session, event)
    await db_session.commit()
    # Idempotency check returns False (already exists)
    assert inserted_second is False

    # Check rollups again: Values must be EXACTLY identical (zero double counting)
    rollup_after_replay = (await db_session.execute(daily_stmt)).scalar_one()
    assert rollup_after_replay.total_tokens == 300
    assert rollup_after_replay.actual_cost == 5000
    assert rollup_after_replay.request_count == 1


@pytest.mark.asyncio
async def test_worker_quarantines_malformed_message():
    """
    Verifies that unparseable or corrupted stream payloads are quarantined
    to the dead-letter stream and ACKed from the main stream, preventing poison-pill blocking.
    """
    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value="dl-msg-1")
    mock_redis.xack = AsyncMock(return_value=1)

    worker = UsageWorkerConsumer(
        redis_client=mock_redis,
        session_factory=AsyncMock(),
        consumer_group="tg-usage-workers",
        consumer_name="worker-dl-test",
    )

    malformed_payload = {"garbage_key": "not a valid usage event"}
    ok = await worker.process_message("1711800000000-99", malformed_payload)

    # Message must be flagged as processed (handled via DLQ)
    assert ok is True

    # Verify dead letter XADD was executed
    mock_redis.xadd.assert_called_once()
    dl_stream = mock_redis.xadd.call_args[0][0]
    assert dl_stream == worker.dead_letter_stream

    # Verify original message was ACKed to unblock the consumer group
    mock_redis.xack.assert_called_once_with(
        worker.stream_name, "tg-usage-workers", "1711800000000-99"
    )
