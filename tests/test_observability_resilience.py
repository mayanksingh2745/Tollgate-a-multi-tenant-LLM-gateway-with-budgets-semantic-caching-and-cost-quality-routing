import uuid

import pytest
from httpx import AsyncClient
from tollgate_core.observability import init_tracer


@pytest.fixture
async def setup_tenant_and_key(async_client: AsyncClient):
    """Helper fixture to create a valid tenant, project, and API key."""
    t_res = await async_client.post(
        "/api/v1/tenants", json={"name": "Resilience Co", "slug": f"res-co-{uuid.uuid4().hex[:6]}"}
    )
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "Resilience Core", "slug": "res-core"},
    )
    project_id = p_res.json()["id"]

    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "Resilience Dev Key"}
    )
    key_data = k_res.json()
    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "api_key_id": key_data["id"],
        "raw_key": key_data["key"],
        "headers": {"Authorization": f"Bearer {key_data['key']}"},
    }


@pytest.mark.asyncio
async def test_otlp_backend_unavailable_does_not_break_requests(
    async_client: AsyncClient, setup_tenant_and_key
):
    """
    CRITICAL INVARIANT (Section 19): Telemetry must never become a hard dependency.
    If the OTLP collector/backend is down or unreachable, the gateway request MUST succeed.
    """
    # Point tracer to a non-existent port on localhost with a short timeout
    init_tracer(
        service_name="tollgate-api",
        enabled=True,
        endpoint="http://127.0.0.1:59999",  # Nothing listening here
        sample_rate=1.0,
        timeout_seconds=0.2,
    )

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Testing non-fatal telemetry failure"}],
    }

    # Request MUST succeed with 200 OK
    res = await async_client.post(
        "/v1/chat/completions",
        headers=setup_tenant_and_key["headers"],
        json=payload,
    )
    assert res.status_code == 200
    data = res.json()
    assert "choices" in data
    assert len(data["choices"]) > 0


@pytest.mark.asyncio
async def test_otel_disabled_graceful_operation(async_client: AsyncClient, setup_tenant_and_key):
    """Verifies gateway functions properly when OTel is explicitly disabled."""
    init_tracer(
        service_name="tollgate-api",
        enabled=False,
    )

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Testing OTel disabled mode"}],
    }

    res = await async_client.post(
        "/v1/chat/completions",
        headers=setup_tenant_and_key["headers"],
        json=payload,
    )
    assert res.status_code == 200
    assert "X-Request-ID" in res.headers
