import pytest
from gateway.src.budgets.metrics import budget_metrics
from gateway.src.providers.mock import MockProvider
from gateway.src.providers.registry import provider_registry
from gateway.src.ratelimit.limiter import rate_limiter
from httpx import AsyncClient


@pytest.fixture
async def setup_pipeline(async_client: AsyncClient):
    # Setup Tenant, Project, API Key
    t = (
        await async_client.post("/api/v1/tenants", json={"name": "Pipe Co", "slug": "pipe-co"})
    ).json()
    p = (
        await async_client.post(
            f"/api/v1/tenants/{t['id']}/projects", json={"name": "Core", "slug": "core"}
        )
    ).json()
    k = (
        await async_client.post(f"/api/v1/projects/{p['id']}/api-keys", json={"name": "Pipe Key"})
    ).json()

    mock = MockProvider(name="pipe_mock")
    provider_registry.register_provider(mock)
    provider_registry.register_route("mock-pipe-model", "pipe_mock", "mock-pipe-model")

    return {
        "tenant_id": t["id"],
        "project_id": p["id"],
        "headers": {"Authorization": f"Bearer {k['key']}"},
        "mock_provider": mock,
    }


@pytest.mark.asyncio
async def test_rate_limit_rejection_prevents_budget_reservation(
    async_client: AsyncClient, setup_pipeline
):
    """
    Section 36: If rate limiting rejects the request (429),
    budget must NOT be reserved.
    """
    data = setup_pipeline
    rate_limiter.burst = 1
    rate_limiter.requests_per_second = 0.01
    rate_limiter.enabled = True

    payload = {"model": "mock-pipe-model", "messages": [{"role": "user", "content": "Hi"}]}

    # 1st request -> ok
    r1 = await async_client.post("/v1/chat/completions", headers=data["headers"], json=payload)
    assert r1.status_code == 200

    before_res_count = budget_metrics.get_count("budget_reservations_total")

    # 2nd request -> 429 Rate Limit Exceeded
    r2 = await async_client.post("/v1/chat/completions", headers=data["headers"], json=payload)
    assert r2.status_code == 429
    assert r2.json()["error"]["code"] == "rate_limit_exceeded"

    # Budget reservation counter must NOT have increased!
    after_res_count = budget_metrics.get_count("budget_reservations_total")
    assert after_res_count == before_res_count


@pytest.mark.asyncio
async def test_budget_rejection_prevents_provider_call(async_client: AsyncClient, setup_pipeline):
    """
    Section 36: If budget rejects the request (402),
    provider must NOT be called.
    """
    data = setup_pipeline
    rate_limiter.burst = 20
    rate_limiter.requests_per_second = 10.0
    rate_limiter.enabled = True

    # Set budget to $0.000001 (1 microdollar)
    await async_client.put(
        f"/api/v1/tenants/{data['tenant_id']}/budget",
        headers=data["headers"],
        json={"monthly_budget_microdollars": 1},
    )

    before_provider_calls = data["mock_provider"].call_count

    payload = {"model": "mock-pipe-model", "messages": [{"role": "user", "content": "Hi"}]}
    r = await async_client.post("/v1/chat/completions", headers=data["headers"], json=payload)

    assert r.status_code == 402
    assert r.json()["error"]["code"] == "budget_exceeded"

    # Provider call count must NOT have increased!
    after_provider_calls = data["mock_provider"].call_count
    assert after_provider_calls == before_provider_calls
