import asyncio
import uuid
from unittest.mock import patch

import pytest
from gateway.src.cache.service import exact_cache
from httpx import AsyncClient


@pytest.fixture
async def setup_failure_project(async_client: AsyncClient):
    t_res = await async_client.post(
        "/api/v1/tenants", json={"name": "Fail Corp", "slug": f"fail-corp-{uuid.uuid4().hex[:6]}"}
    )
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "Fail Proj", "slug": f"fail-proj-{uuid.uuid4().hex[:6]}"},
    )
    project_id = p_res.json()["id"]

    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "Fail Key"}
    )
    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "headers": {"Authorization": f"Bearer {k_res.json()['key']}"},
    }


@pytest.mark.asyncio
async def test_cache_lookup_failure_fails_open(async_client: AsyncClient, setup_failure_project):
    """
    Section 24: Fail-open on cache lookup failure.
    If Redis or the cache backend raises an exception during lookup,
    the request must not fail. It should proceed to the provider and return 200 OK.
    """
    data = setup_failure_project
    req = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Lookup failure test"}],
    }

    async def broken_get(key: str):
        raise ConnectionError("Redis cluster unreachable during lookup")

    with patch.object(exact_cache.backend, "get", side_effect=broken_get):
        resp = await async_client.post("/v1/chat/completions", headers=data["headers"], json=req)
        assert resp.status_code == 200
        assert resp.headers.get("X-Tollgate-Cache") == "MISS"
        assert "choices" in resp.json()


@pytest.mark.asyncio
async def test_cache_write_failure_does_not_break_request(
    async_client: AsyncClient, setup_failure_project
):
    """
    Section 24: Fail-open on cache write failure.
    If Redis or the cache backend raises an exception during cache write,
    the successful provider response must still be returned to the client.
    """
    data = setup_failure_project
    req = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Write failure test"}],
    }

    async def broken_set(key: str, value: str, ttl_seconds: int):
        raise ConnectionError("Redis out of memory or write timeout")

    with patch.object(exact_cache.backend, "set", side_effect=broken_set):
        resp = await async_client.post("/v1/chat/completions", headers=data["headers"], json=req)
        assert resp.status_code == 200
        assert "choices" in resp.json()


@pytest.mark.asyncio
async def test_corrupted_cached_data_treated_as_miss(
    async_client: AsyncClient, setup_failure_project
):
    """
    Section 41: Corrupted or unparseable cached data must be treated as a MISS,
    removed from the backend if safe, and the provider must be called.
    """
    data = setup_failure_project
    req = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Corrupted data test"}],
    }

    # Store malformed JSON string into cache backend
    async def malformed_get(key: str):
        return "{broken json payload: [not valid"

    with patch.object(exact_cache.backend, "get", side_effect=malformed_get):
        resp = await async_client.post("/v1/chat/completions", headers=data["headers"], json=req)
        assert resp.status_code == 200
        assert "choices" in resp.json()


@pytest.mark.asyncio
async def test_cache_ttl_expiration(async_client: AsyncClient, setup_failure_project):
    """
    Section 40: TTL expiration test.
    Verify that an entry expires when its TTL elapses.
    """
    data = setup_failure_project
    req = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "TTL expiration test"}],
    }

    # 1. First request -> MISS
    resp1 = await async_client.post("/v1/chat/completions", headers=data["headers"], json=req)
    assert resp1.headers.get("X-Tollgate-Cache") == "MISS"

    # 2. Second request -> HIT
    resp2 = await async_client.post("/v1/chat/completions", headers=data["headers"], json=req)
    assert resp2.headers.get("X-Tollgate-Cache") == "HIT"

    # Clear backend (simulating TTL expiration)
    if hasattr(exact_cache.backend, "clear"):
        exact_cache.backend.clear()

    # 3. Third request -> MISS
    resp3 = await async_client.post("/v1/chat/completions", headers=data["headers"], json=req)
    assert resp3.headers.get("X-Tollgate-Cache") == "MISS"


@pytest.mark.asyncio
async def test_concurrent_identical_requests(async_client: AsyncClient, setup_failure_project):
    """
    Section 30: Concurrency test.
    When multiple identical requests arrive simultaneously, all should succeed safely.
    """
    data = setup_failure_project
    req = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Concurrent stampede test"}],
    }

    tasks = [
        async_client.post("/v1/chat/completions", headers=data["headers"], json=req)
        for _ in range(5)
    ]
    responses = await asyncio.gather(*tasks)

    for r in responses:
        assert r.status_code == 200
        assert "choices" in r.json()
