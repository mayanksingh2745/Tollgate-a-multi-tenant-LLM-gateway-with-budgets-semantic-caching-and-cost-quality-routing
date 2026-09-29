import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import Project, Tenant, UsageEvent
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.consumer import UsageWorkerConsumer


@pytest.mark.asyncio
async def test_worker_consumer_group_creation():
    mock_redis = AsyncMock()
    consumer = UsageWorkerConsumer(
        redis_client=mock_redis,
        session_factory=AsyncMock(),
        consumer_group="tg-test-group",
        stream_name="tg:test:stream",
    )

    # 1. Successful group creation
    await consumer.ensure_consumer_group()
    mock_redis.xgroup_create.assert_called_once_with(
        "tg:test:stream", "tg-test-group", id="0", mkstream=True
    )

    # 2. BUSYGROUP error (already exists) handled safely without exception
    mock_redis.xgroup_create.side_effect = Exception("BUSYGROUP Consumer Group name already exists")
    await consumer.ensure_consumer_group()


@pytest.mark.asyncio
async def test_worker_process_valid_message(db_session: AsyncSession):
    t_id = uuid.uuid4()
    p_id = uuid.uuid4()
    tenant = Tenant(id=t_id, name="Worker Tenant", slug="worker-tenant")
    project = Project(id=p_id, tenant_id=t_id, name="Worker Project", slug="worker-proj")
    db_session.add_all([tenant, project])
    await db_session.commit()

    event = UsageEventPayload(
        event_id=uuid.uuid4(),
        request_id="req_worker_1",
        timestamp=datetime.now(timezone.utc),
        tenant_id=t_id,
        project_id=p_id,
        provider="openai",
        model="gpt-4o",
        status="success",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        estimated_cost=2000,
        actual_cost=1500,
    )

    mock_redis = AsyncMock()

    # Dummy session factory returning db_session
    class DummyContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *args):
            pass

    def mock_session_factory():
        return DummyContext()

    consumer = UsageWorkerConsumer(
        redis_client=mock_redis,
        session_factory=mock_session_factory,
    )

    entry = event.to_stream_entry()
    success = await consumer.process_message("1000-0", entry)
    assert success is True

    # Check XACK was called
    mock_redis.xack.assert_called_once_with(consumer.stream_name, consumer.consumer_group, "1000-0")

    # Check DB was committed and records exist
    events = (
        (await db_session.execute(select(UsageEvent).where(UsageEvent.tenant_id == t_id)))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].event_id == event.event_id


@pytest.mark.asyncio
async def test_worker_quarantine_malformed_message():
    mock_redis = AsyncMock()
    consumer = UsageWorkerConsumer(
        redis_client=mock_redis,
        session_factory=AsyncMock(),
    )

    malformed_entry = {"data": json.dumps({"invalid": "missing required fields"})}

    success = await consumer.process_message("1001-0", malformed_entry)
    assert success is True

    # Quarantined to dead letter stream
    mock_redis.xadd.assert_called_once()
    args, kwargs = mock_redis.xadd.call_args
    assert args[0] == consumer.dead_letter_stream

    # And ACKed to unblock the main stream
    mock_redis.xack.assert_called_once_with(consumer.stream_name, consumer.consumer_group, "1001-0")


@pytest.mark.asyncio
async def test_worker_reclaims_stale_messages():
    mock_redis = AsyncMock()
    consumer = UsageWorkerConsumer(
        redis_client=mock_redis,
        session_factory=AsyncMock(),
        claim_idle_seconds=60,
    )

    mock_redis.xautoclaim.return_value = (
        "0-0",
        [],
        [],
    )

    count = await consumer.reclaim_stale_messages()
    assert count == 0
    mock_redis.xautoclaim.assert_called_once_with(
        consumer.stream_name,
        consumer.consumer_group,
        consumer.consumer_name,
        min_idle_time=60000,
        start_id="0-0",
        count=consumer.batch_size,
    )
