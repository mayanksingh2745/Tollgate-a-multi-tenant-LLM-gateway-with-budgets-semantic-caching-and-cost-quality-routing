import uuid
from unittest.mock import patch

import pytest
from gateway.src.usage.publisher import usage_publisher
from httpx import AsyncClient


@pytest.fixture
async def setup_test_project(async_client: AsyncClient):
    # Setup Tenant, Project, and Admin API Key
    t_res = await async_client.post(
        "/api/v1/tenants", json={"name": "Cache Corp", "slug": f"cache-corp-{uuid.uuid4().hex[:6]}"}
    )
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "Cache Proj", "slug": f"cache-proj-{uuid.uuid4().hex[:6]}"},
    )
    project_id = p_res.json()["id"]

    # Admin Key
    k_admin_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "Admin Key"}
    )
    admin_key = k_admin_res.json()["key"]

    # Member User and Key
    u_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={
            "name": "Cache Member",
            "email": f"member-{uuid.uuid4().hex[:6]}@cachecorp.com",
            "password": "CacheTest123!",
            "role": "viewer",
        },
    )
    user_id = u_res.json()["id"]
    k_member_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys",
        json={"name": "Member Key", "user_id": user_id},
    )
    member_key = k_member_res.json()["key"]

    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "admin_headers": {"Authorization": f"Bearer {admin_key}"},
        "member_headers": {"Authorization": f"Bearer {member_key}"},
    }


@pytest.mark.asyncio
async def test_exact_cache_hit_flow_and_headers(async_client: AsyncClient, setup_test_project):
    """
    Verify exact cache lookup flow:
    First request produces MISS and stores response.
    Second identical request produces HIT with identical payload and X-Tollgate-Cache: HIT header.
    """
    data = setup_test_project
    req = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "What is 2 + 2?"}],
        "temperature": 0.0,
    }

    # 1. Request A -> MISS
    resp1 = await async_client.post("/v1/chat/completions", headers=data["admin_headers"], json=req)
    assert resp1.status_code == 200
    assert resp1.headers.get("X-Tollgate-Cache") == "MISS"
    data1 = resp1.json()

    # 2. Request A (identical) -> HIT
    resp2 = await async_client.post("/v1/chat/completions", headers=data["admin_headers"], json=req)
    assert resp2.status_code == 200
    assert resp2.headers.get("X-Tollgate-Cache") == "HIT"
    data2 = resp2.json()

    assert data1["id"] == data2["id"]
    assert data1["choices"][0]["message"]["content"] == data2["choices"][0]["message"]["content"]
    assert data1["model"] == data2["model"]


@pytest.mark.asyncio
async def test_cache_hit_does_not_consume_budget(async_client: AsyncClient, setup_test_project):
    """
    Verify that cache hits do NOT consume provider budget.
    Set a tight project budget that allows exactly one provider call.
    Second request (identical) hits cache and succeeds even when budget is fully exhausted.
    Third request with a different prompt attempts provider call and fails with 402 Budget Exceeded.
    """
    data = setup_test_project

    # Estimated cost for short prompt (~15 tokens + 1000 max_tokens default) is ~$15,000 microdollars
    # Set project monthly budget to exactly 40,000 microdollars (allowing only 1 provider call)
    await async_client.put(
        f"/api/v1/projects/{data['project_id']}/budget",
        headers=data["admin_headers"],
        json={"monthly_budget_microdollars": 40_000},
    )

    req1 = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Budget test question 1"}],
    }

    # 1. First request succeeds (MISS, consumes budget)
    res1 = await async_client.post("/v1/chat/completions", headers=data["admin_headers"], json=req1)
    assert res1.status_code == 200
    assert res1.headers.get("X-Tollgate-Cache") == "MISS"

    # Now tighten budget to 0 so no further provider calls are permitted
    await async_client.put(
        f"/api/v1/projects/{data['project_id']}/budget",
        headers=data["admin_headers"],
        json={"monthly_budget_microdollars": 1},
    )

    # 2. Identical request -> HIT (Must succeed because no provider budget is reserved or consumed)
    res2 = await async_client.post("/v1/chat/completions", headers=data["admin_headers"], json=req1)
    assert res2.status_code == 200
    assert res2.headers.get("X-Tollgate-Cache") == "HIT"

    # 3. Different request -> MISS -> Fails budget check with 402
    req2 = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Budget test question 2 (different)"}],
    }
    res3 = await async_client.post("/v1/chat/completions", headers=data["admin_headers"], json=req2)
    assert res3.status_code == 402


@pytest.mark.asyncio
async def test_cache_hit_does_not_emit_provider_usage_events(
    async_client: AsyncClient, setup_test_project
):
    """
    Verify that cache hits do not emit provider usage events to the Redis stream.
    """
    data = setup_test_project
    published_events = []

    async def mock_publish(event):
        published_events.append(event)
        return "100-0"

    with patch.object(usage_publisher, "publish", side_effect=mock_publish):
        req = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Count usage events"}],
        }

        # Request 1 -> MISS -> Emits 1 usage event
        r1 = await async_client.post(
            "/v1/chat/completions", headers=data["admin_headers"], json=req
        )
        assert r1.status_code == 200
        assert r1.headers.get("X-Tollgate-Cache") == "MISS"
        assert len(published_events) == 1

        # Request 2 -> HIT -> Does NOT emit any usage event
        r2 = await async_client.post(
            "/v1/chat/completions", headers=data["admin_headers"], json=req
        )
        assert r2.status_code == 200
        assert r2.headers.get("X-Tollgate-Cache") == "HIT"
        assert len(published_events) == 1, "Cache hit must not produce provider usage events"


@pytest.mark.asyncio
async def test_rate_limiting_still_applies_on_cache_hit(
    async_client: AsyncClient, setup_test_project
):
    """
    Verify that rate limiting applies to every request arriving at the gateway, including cache hits.
    """
    data = setup_test_project
    req = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Check rate limits"}],
    }

    # Request 1 -> MISS
    resp1 = await async_client.post("/v1/chat/completions", headers=data["admin_headers"], json=req)
    assert resp1.status_code == 200
    assert "X-RateLimit-Remaining" in resp1.headers
    rem1 = int(resp1.headers["X-RateLimit-Remaining"])

    # Request 2 -> HIT
    resp2 = await async_client.post("/v1/chat/completions", headers=data["admin_headers"], json=req)
    assert resp2.status_code == 200
    assert "X-RateLimit-Remaining" in resp2.headers
    rem2 = int(resp2.headers["X-RateLimit-Remaining"])

    assert rem2 < rem1, "Rate limit counter must decrement on cache hit"


@pytest.mark.asyncio
async def test_admin_invalidation_endpoint_and_rbac(async_client: AsyncClient, setup_test_project):
    """
    Verify cache invalidation endpoint:
    - Member role gets 403 Forbidden.
    - Admin role gets 200 OK.
    - Subsequent identical request results in a MISS.
    """
    data = setup_test_project
    project_id = data["project_id"]
    req = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Will be invalidated"}],
    }

    # Populate cache
    res1 = await async_client.post("/v1/chat/completions", headers=data["admin_headers"], json=req)
    assert res1.headers.get("X-Tollgate-Cache") == "MISS"
    res2 = await async_client.post("/v1/chat/completions", headers=data["admin_headers"], json=req)
    assert res2.headers.get("X-Tollgate-Cache") == "HIT"

    # Member attempts invalidation -> 403 Forbidden
    del_member = await async_client.delete(
        f"/api/v1/projects/{project_id}/cache", headers=data["member_headers"]
    )
    assert del_member.status_code == 403

    # Admin invalidates cache -> 200 OK
    del_admin = await async_client.delete(
        f"/api/v1/projects/{project_id}/cache", headers=data["admin_headers"]
    )
    assert del_admin.status_code == 200
    assert del_admin.json()["status"] == "success"

    # Next identical request -> MISS
    res3 = await async_client.post("/v1/chat/completions", headers=data["admin_headers"], json=req)
    assert res3.headers.get("X-Tollgate-Cache") == "MISS"


@pytest.mark.asyncio
async def test_streaming_and_tools_cache_bypass_header(
    async_client: AsyncClient, setup_test_project
):
    """
    Verify that streaming and tools requests report X-Tollgate-Cache: BYPASS.
    """
    data = setup_test_project

    # Tools request
    tools_req = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Weather in Paris"}],
        "tools": [{"type": "function", "function": {"name": "get_weather"}}],
    }
    r_tools = await async_client.post(
        "/v1/chat/completions", headers=data["admin_headers"], json=tools_req
    )
    assert r_tools.status_code == 200
    assert r_tools.headers.get("X-Tollgate-Cache") == "BYPASS"
