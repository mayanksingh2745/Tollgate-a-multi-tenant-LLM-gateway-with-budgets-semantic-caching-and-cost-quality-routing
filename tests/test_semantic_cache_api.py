from unittest.mock import AsyncMock, patch

import pytest
from gateway.src.config import settings
from gateway.src.usage.publisher import usage_publisher
from httpx import AsyncClient


async def create_tenant_and_project(client: AsyncClient, name: str):
    t_res = await client.post(
        "/api/v1/tenants", json={"name": f"{name} Tenant", "slug": f"{name.lower()}-tenant"}
    )
    assert t_res.status_code == 201
    tenant_id = t_res.json()["id"]

    p_res = await client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": f"{name} Project", "slug": f"{name.lower()}-proj"},
    )
    assert p_res.status_code == 201
    project_id = p_res.json()["id"]

    k_res = await client.post(f"/api/v1/projects/{project_id}/api-keys", json={"name": "Test Key"})
    assert k_res.status_code == 201
    secret_key = k_res.json()["key"]

    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "headers": {"Authorization": f"Bearer {secret_key}"},
    }


@pytest.mark.asyncio
async def test_semantic_cache_hit_and_accounting(async_client: AsyncClient):
    with (
        patch.object(settings, "semantic_cache_enabled", True),
        patch.object(settings, "semantic_cache_threshold", 0.85),
    ):
        t = await create_tenant_and_project(async_client, "accounting")

        # Request 1: Cold Cache
        with patch.object(usage_publisher, "publish", new_callable=AsyncMock) as mock_pub:
            resp1 = await async_client.post(
                "/v1/chat/completions",
                json={
                    "model": "mock-model",
                    "messages": [
                        {
                            "role": "user",
                            "content": "How does TCP congestion control work?",
                        }
                    ],
                },
                headers=t["headers"],
            )
            assert resp1.status_code == 200
            assert resp1.headers.get("X-Tollgate-Cache") == "MISS"
            assert mock_pub.call_count == 1  # Provider usage event published

        # Request 2: Semantically Equivalent Prompt -> Semantic HIT
        with patch.object(usage_publisher, "publish", new_callable=AsyncMock) as mock_pub:
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
            assert resp2.status_code == 200
            assert resp2.headers.get("X-Tollgate-Cache") == "SEMANTIC_HIT"
            # Section 25 & 26: Zero provider usage events on semantic cache hit
            assert mock_pub.call_count == 0


@pytest.mark.asyncio
async def test_semantic_cache_shadow_mode(async_client: AsyncClient):
    with (
        patch.object(settings, "semantic_cache_enabled", True),
        patch.object(settings, "semantic_cache_shadow_mode", True),
        patch.object(settings, "semantic_cache_threshold", 0.85),
    ):
        t = await create_tenant_and_project(async_client, "shadow")

        # Request 1: Warm cache
        resp1 = await async_client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [
                    {
                        "role": "user",
                        "content": "How does TCP congestion control work?",
                    }
                ],
            },
            headers=t["headers"],
        )
        assert resp1.status_code == 200

        # Request 2: Similar prompt in shadow mode
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
        assert resp2.status_code == 200
        # In shadow mode, cached response is NOT returned
        assert resp2.headers.get("X-Tollgate-Cache") == "MISS"


@pytest.mark.asyncio
async def test_semantic_cache_hit_with_exhausted_budget(async_client: AsyncClient):
    with (
        patch.object(settings, "semantic_cache_enabled", True),
        patch.object(settings, "semantic_cache_threshold", 0.85),
    ):
        t = await create_tenant_and_project(async_client, "zero-budget")

        # 1. Warm cache
        resp1 = await async_client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [
                    {
                        "role": "user",
                        "content": "How does TCP congestion control work?",
                    }
                ],
            },
            headers=t["headers"],
        )
        assert resp1.status_code == 200

        # 2. Set project budget to 1 microdollar so budget is exhausted
        b_res = await async_client.put(
            f"/api/v1/projects/{t['project_id']}/budget",
            json={"monthly_budget_microdollars": 1},
            headers=t["headers"],
        )
        assert b_res.status_code == 200

        # 3. New un-cached query fails with 402 Payment Required
        fail_resp = await async_client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": "Tell me about quantum computing."}],
            },
            headers=t["headers"],
        )
        assert fail_resp.status_code == 402

        # 4. Semantically cached query succeeds with 200 and SEMANTIC_HIT
        hit_resp = await async_client.post(
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
        assert hit_resp.status_code == 200
        assert hit_resp.headers.get("X-Tollgate-Cache") == "SEMANTIC_HIT"


@pytest.mark.asyncio
async def test_cache_invalidation_and_inspection_api(async_client: AsyncClient):
    with (
        patch.object(settings, "semantic_cache_enabled", True),
        patch.object(settings, "semantic_cache_threshold", 0.85),
    ):
        t = await create_tenant_and_project(async_client, "invalidation")

        # Warm cache
        resp1 = await async_client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [
                    {
                        "role": "user",
                        "content": "How does TCP congestion control work?",
                    }
                ],
            },
            headers=t["headers"],
        )
        assert resp1.status_code == 200

        # Inspect semantic cache metadata
        inspect_res = await async_client.get(
            f"/api/v1/projects/{t['project_id']}/cache/semantic",
            headers=t["headers"],
        )
        assert inspect_res.status_code == 200
        items = inspect_res.json()
        assert len(items) == 1
        assert items[0]["model"] == "mock-model"
        assert "embedding" not in items[0]  # Vectors not exposed

        # Invalidate project cache
        del_res = await async_client.delete(
            f"/api/v1/projects/{t['project_id']}/cache",
            headers=t["headers"],
        )
        assert del_res.status_code == 200
        del_data = del_res.json()
        assert del_data["status"] == "success"
        assert "semantic_entries_invalidated" in del_data

        # Next similar request must be a MISS
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
        assert resp2.status_code == 200
        assert resp2.headers.get("X-Tollgate-Cache") == "MISS"
