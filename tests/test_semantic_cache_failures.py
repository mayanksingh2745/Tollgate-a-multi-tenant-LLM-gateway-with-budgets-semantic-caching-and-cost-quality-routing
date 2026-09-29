import asyncio
from unittest.mock import patch

import pytest
from gateway.src.cache.semantic.service import semantic_cache
from gateway.src.cache.service import exact_cache
from gateway.src.config import settings
from httpx import AsyncClient


async def create_test_tenant_and_key(client: AsyncClient, slug: str):
    t_res = await client.post("/api/v1/tenants", json={"name": slug, "slug": slug})
    tenant_id = t_res.json()["id"]
    p_res = await client.post(
        f"/api/v1/tenants/{tenant_id}/projects", json={"name": slug, "slug": slug}
    )
    project_id = p_res.json()["id"]
    k_res = await client.post(f"/api/v1/projects/{project_id}/api-keys", json={"name": "Key"})
    secret_key = k_res.json()["key"]
    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "headers": {"Authorization": f"Bearer {secret_key}"},
    }


@pytest.mark.asyncio
async def test_fail_open_on_embedding_provider_error(async_client: AsyncClient):
    with patch.object(settings, "semantic_cache_enabled", True):
        t = await create_test_tenant_and_key(async_client, "fail-emb-err")

        # Mock embedding provider raising an unhandled exception
        with patch.object(
            semantic_cache.embedding_provider,
            "embed",
            side_effect=RuntimeError("Embedding API connection error"),
        ):
            resp = await async_client.post(
                "/v1/chat/completions",
                json={
                    "model": "mock-model",
                    "messages": [{"role": "user", "content": "Explain TCP"}],
                },
                headers=t["headers"],
            )
            # Gateway must fail open and return 200 via normal provider path
            assert resp.status_code == 200
            assert "choices" in resp.json()
            assert resp.headers.get("X-Tollgate-Cache") == "MISS"


@pytest.mark.asyncio
async def test_fail_open_on_embedding_timeout(async_client: AsyncClient):
    with (
        patch.object(settings, "semantic_cache_enabled", True),
        patch.object(settings, "embedding_timeout_seconds", 0.05),
    ):
        t = await create_test_tenant_and_key(async_client, "fail-emb-timeout")

        async def slow_embed(*args, **kwargs):
            await asyncio.sleep(0.5)
            return [0.0] * 1536

        with patch.object(semantic_cache.embedding_provider, "embed", side_effect=slow_embed):
            resp = await async_client.post(
                "/v1/chat/completions",
                json={
                    "model": "mock-model",
                    "messages": [{"role": "user", "content": "Explain TCP"}],
                },
                headers=t["headers"],
            )
            assert resp.status_code == 200
            assert "choices" in resp.json()
            assert resp.headers.get("X-Tollgate-Cache") == "MISS"


@pytest.mark.asyncio
async def test_fail_open_on_database_search_error(async_client: AsyncClient):
    with patch.object(settings, "semantic_cache_enabled", True):
        t = await create_test_tenant_and_key(async_client, "fail-db-search")

        with patch.object(
            semantic_cache.backend,
            "search_candidates",
            side_effect=Exception("Database connection terminated"),
        ):
            resp = await async_client.post(
                "/v1/chat/completions",
                json={
                    "model": "mock-model",
                    "messages": [{"role": "user", "content": "Explain TCP"}],
                },
                headers=t["headers"],
            )
            assert resp.status_code == 200
            assert resp.headers.get("X-Tollgate-Cache") == "MISS"


@pytest.mark.asyncio
async def test_fail_open_on_stale_redis_reference(async_client: AsyncClient):
    with (
        patch.object(settings, "semantic_cache_enabled", True),
        patch.object(settings, "semantic_cache_threshold", 0.85),
    ):
        t = await create_test_tenant_and_key(async_client, "fail-stale-ref")

        # 1. Warm cache
        resp1 = await async_client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": "How does TCP congestion control work?"}],
            },
            headers=t["headers"],
        )
        assert resp1.status_code == 200

        # 2. Simulate Redis response eviction by clearing exact cache store
        exact_cache.backend.clear()

        # 3. Next similar request encounters stale semantic reference
        resp2 = await async_client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [
                    {
                        "role": "user",
                        "content": "Can you explain the mechanism behind TCP congestion control?",
                    }
                ],
            },
            headers=t["headers"],
        )
        # Fails open: treats as MISS and calls provider without failing the user
        assert resp2.status_code == 200
        assert resp2.headers.get("X-Tollgate-Cache") == "MISS"
