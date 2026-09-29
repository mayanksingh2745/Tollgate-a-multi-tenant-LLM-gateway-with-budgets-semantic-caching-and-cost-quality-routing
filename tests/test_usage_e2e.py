import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from gateway.src.usage.publisher import usage_publisher
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.consumer import UsageWorkerConsumer


@pytest.fixture
async def setup_e2e_tenant(async_client: AsyncClient):
    t_res = await async_client.post("/api/v1/tenants", json={"name": "E2E Co", "slug": "e2e-co"})
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects", json={"name": "E2E Proj", "slug": "e2e-proj"}
    )
    project_id = p_res.json()["id"]

    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "E2E Key"}
    )
    key_data = k_res.json()
    return {
        "tenant_id": uuid.UUID(tenant_id),
        "project_id": uuid.UUID(project_id),
        "headers": {"Authorization": f"Bearer {key_data['key']}"},
    }


@pytest.mark.asyncio
async def test_e2e_gateway_to_worker_to_query_api(
    async_client: AsyncClient, db_session: AsyncSession, setup_e2e_tenant
):
    """
    End-to-End Test:
    Client calls /v1/chat/completions -> Gateway settles budget and emits usage event
    -> Worker consumes event from Redis Stream -> Worker persists to DB -> Client queries /api/v1/usage
    """
    published_events = []

    async def mock_publish(event: UsageEventPayload):
        published_events.append(event)
        return "100-0"

    with patch.object(usage_publisher, "publish", side_effect=mock_publish):
        payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Calculate test tokens"}],
        }
        resp = await async_client.post(
            "/v1/chat/completions",
            headers=setup_e2e_tenant["headers"],
            json=payload,
        )
        assert resp.status_code == 200

    assert len(published_events) == 1
    event = published_events[0]
    assert event.status == "success"
    assert event.model == "mock-model"
    assert event.tenant_id == setup_e2e_tenant["tenant_id"]
    assert event.project_id == setup_e2e_tenant["project_id"]
    assert event.total_tokens > 0
    assert event.actual_cost >= 0

    # Worker consumes this event
    class DummyContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *args):
            pass

    mock_redis = AsyncMock()
    consumer = UsageWorkerConsumer(
        redis_client=mock_redis,
        session_factory=lambda: DummyContext(),
    )

    msg_id = "100-0"
    processed = await consumer.process_message(msg_id, event.to_stream_entry())
    assert processed is True
    await db_session.commit()

    # Client queries /api/v1/usage
    query_resp = await async_client.get("/api/v1/usage", headers=setup_e2e_tenant["headers"])
    assert query_resp.status_code == 200
    usage_list = query_resp.json()["items"]
    assert len(usage_list) == 1
    record = usage_list[0]
    assert record["event_id"] == str(event.event_id)
    assert record["request_id"] == event.request_id
    assert record["total_tokens"] == event.total_tokens
    assert record["actual_cost"] == event.actual_cost

    # Client queries /api/v1/usage/rollups/daily
    daily_resp = await async_client.get(
        "/api/v1/usage/rollups/daily", headers=setup_e2e_tenant["headers"]
    )
    assert daily_resp.status_code == 200
    rollups = daily_resp.json()
    assert len(rollups) == 1
    assert rollups[0]["request_count"] == 1
    assert rollups[0]["total_tokens"] == event.total_tokens


@pytest.mark.asyncio
async def test_failure_injection_reclaim_and_idempotency(
    async_client: AsyncClient, db_session: AsyncSession, setup_e2e_tenant
):
    """
    Failure Injection:
    1. Worker crash simulation where message is re-delivered (duplicate delivery)
    2. Verification that rollup does not double-count
    """

    class DummyContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *args):
            pass

    mock_redis = AsyncMock()
    consumer = UsageWorkerConsumer(
        redis_client=mock_redis,
        session_factory=lambda: DummyContext(),
    )

    event_id = uuid.uuid4()
    event = UsageEventPayload(
        event_id=event_id,
        request_id="req_fail_inject",
        timestamp=datetime.now(timezone.utc),
        tenant_id=setup_e2e_tenant["tenant_id"],
        project_id=setup_e2e_tenant["project_id"],
        provider="openai",
        model="gpt-4o",
        status="success",
        input_tokens=50,
        output_tokens=25,
        total_tokens=75,
        estimated_cost=1000,
        actual_cost=800,
    )

    # 1. First delivery
    ok1 = await consumer.process_message("200-0", event.to_stream_entry())
    assert ok1 is True
    await db_session.commit()

    # 2. Worker crashed before ACK or redelivered message (XCLAIM/XAUTOCLAIM)
    ok2 = await consumer.process_message("200-0", event.to_stream_entry())
    assert ok2 is True
    await db_session.commit()

    # 3. Verify exactly 1 usage record exists and rollup is 1, not 2
    query_resp = await async_client.get("/api/v1/usage", headers=setup_e2e_tenant["headers"])
    assert len(query_resp.json()["items"]) == 1

    daily_resp = await async_client.get(
        "/api/v1/usage/rollups/daily", headers=setup_e2e_tenant["headers"]
    )
    assert daily_resp.json()[0]["request_count"] == 1
    assert daily_resp.json()[0]["actual_cost"] == 800
