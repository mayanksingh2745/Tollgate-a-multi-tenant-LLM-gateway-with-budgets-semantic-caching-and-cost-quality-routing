import pytest
from gateway.src.providers.mock import MockProvider
from gateway.src.providers.registry import provider_registry
from gateway.src.ratelimit.limiter import rate_limiter
from httpx import AsyncClient


@pytest.fixture
async def setup_two_keys(async_client: AsyncClient):
    """Helper fixture to create two distinct API keys for isolation tests."""
    t_res = await async_client.post("/api/v1/tenants", json={"name": "RL Co", "slug": "rl-co"})
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects", json={"name": "Core", "slug": "core"}
    )
    project_id = p_res.json()["id"]

    k1_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "Key 1"}
    )
    k1 = k1_res.json()

    k2_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "Key 2"}
    )
    k2 = k2_res.json()

    # Register default mock provider for mock-model
    provider_registry.register_provider(MockProvider(name="mock_rl"))
    provider_registry.register_route("mock-model", "mock_rl", "mock-model")

    return {
        "headers_1": {"Authorization": f"Bearer {k1['key']}"},
        "headers_2": {"Authorization": f"Bearer {k2['key']}"},
    }


@pytest.mark.asyncio
async def test_rate_limit_headers_on_success(async_client: AsyncClient, setup_two_keys):
    rate_limiter.burst = 10
    rate_limiter.requests_per_second = 5.0
    rate_limiter.enabled = True

    payload = {"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]}
    res = await async_client.post(
        "/v1/chat/completions", headers=setup_two_keys["headers_1"], json=payload
    )

    assert res.status_code == 200
    assert "x-ratelimit-limit" in res.headers
    assert res.headers["x-ratelimit-limit"] == "10"
    assert "x-ratelimit-remaining" in res.headers
    assert int(res.headers["x-ratelimit-remaining"]) == 9
    assert "x-ratelimit-reset" in res.headers


@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_429(async_client: AsyncClient, setup_two_keys):
    rate_limiter.burst = 2
    rate_limiter.requests_per_second = 0.1  # very slow refill
    rate_limiter.enabled = True

    payload = {"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]}

    # 1st request -> ok
    r1 = await async_client.post(
        "/v1/chat/completions", headers=setup_two_keys["headers_1"], json=payload
    )
    assert r1.status_code == 200
    assert r1.headers["x-ratelimit-remaining"] == "1"

    # 2nd request -> ok
    r2 = await async_client.post(
        "/v1/chat/completions", headers=setup_two_keys["headers_1"], json=payload
    )
    assert r2.status_code == 200
    assert r2.headers["x-ratelimit-remaining"] == "0"

    # 3rd request -> 429 Rate Limit Exceeded
    r3 = await async_client.post(
        "/v1/chat/completions", headers=setup_two_keys["headers_1"], json=payload
    )
    assert r3.status_code == 429
    assert r3.headers["x-ratelimit-remaining"] == "0"
    assert "retry-after" in r3.headers
    assert int(r3.headers["retry-after"]) >= 1

    body = r3.json()
    assert "error" in body
    assert body["error"]["type"] == "rate_limit_error"
    assert body["error"]["code"] == "rate_limit_exceeded"
    assert "Rate limit exceeded" in body["error"]["message"]


@pytest.mark.asyncio
async def test_rate_limit_api_key_isolation(async_client: AsyncClient, setup_two_keys):
    rate_limiter.burst = 1
    rate_limiter.requests_per_second = 0.1
    rate_limiter.enabled = True

    payload = {"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]}

    # Exhaust Key 1
    r1 = await async_client.post(
        "/v1/chat/completions", headers=setup_two_keys["headers_1"], json=payload
    )
    assert r1.status_code == 200

    r1_blocked = await async_client.post(
        "/v1/chat/completions", headers=setup_two_keys["headers_1"], json=payload
    )
    assert r1_blocked.status_code == 429

    # Key 2 should still be completely unaffected and succeed!
    r2 = await async_client.post(
        "/v1/chat/completions", headers=setup_two_keys["headers_2"], json=payload
    )
    assert r2.status_code == 200
    assert r2.headers["x-ratelimit-remaining"] == "0"


@pytest.mark.asyncio
async def test_rate_limit_streaming(async_client: AsyncClient, setup_two_keys):
    rate_limiter.burst = 1
    rate_limiter.requests_per_second = 0.1
    rate_limiter.enabled = True

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True,
    }

    # 1st streaming request -> 200
    r1 = await async_client.post(
        "/v1/chat/completions", headers=setup_two_keys["headers_1"], json=payload
    )
    assert r1.status_code == 200
    assert "text/event-stream" in r1.headers["content-type"]
    assert "x-ratelimit-remaining" in r1.headers

    # 2nd streaming request -> 429 before streaming begins
    r2 = await async_client.post(
        "/v1/chat/completions", headers=setup_two_keys["headers_1"], json=payload
    )
    assert r2.status_code == 429
    assert r2.json()["error"]["code"] == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_rate_limit_disabled(async_client: AsyncClient, setup_two_keys):
    rate_limiter.burst = 1
    rate_limiter.requests_per_second = 0.1
    rate_limiter.enabled = False  # Disabled

    payload = {"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]}

    # Multiple requests succeed without rate limiting
    for _ in range(5):
        r = await async_client.post(
            "/v1/chat/completions", headers=setup_two_keys["headers_1"], json=payload
        )
        assert r.status_code == 200
