from unittest.mock import patch

import pytest
from gateway.src.config import settings
from httpx import AsyncClient


async def create_tenant_hierarchy(client: AsyncClient, name_prefix: str):
    t_res = await client.post(
        "/api/v1/tenants",
        json={"name": f"{name_prefix} Org", "slug": f"{name_prefix.lower()}-org"},
    )
    assert t_res.status_code == 201
    tenant_id = t_res.json()["id"]

    p1_res = await client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": f"{name_prefix} Proj A", "slug": f"{name_prefix.lower()}-proj-a"},
    )
    assert p1_res.status_code == 201
    proj_a_id = p1_res.json()["id"]

    p2_res = await client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": f"{name_prefix} Proj B", "slug": f"{name_prefix.lower()}-proj-b"},
    )
    assert p2_res.status_code == 201
    proj_b_id = p2_res.json()["id"]

    k1_res = await client.post(
        f"/api/v1/projects/{proj_a_id}/api-keys",
        json={"name": "Key A1"},
    )
    assert k1_res.status_code == 201
    key_a1 = k1_res.json()["key"]

    k2_res = await client.post(
        f"/api/v1/projects/{proj_a_id}/api-keys",
        json={"name": "Key A2"},
    )
    assert k2_res.status_code == 201
    key_a2 = k2_res.json()["key"]

    kb_res = await client.post(
        f"/api/v1/projects/{proj_b_id}/api-keys",
        json={"name": "Key B"},
    )
    assert kb_res.status_code == 201
    key_b = kb_res.json()["key"]

    return {
        "tenant_id": tenant_id,
        "proj_a_id": proj_a_id,
        "proj_b_id": proj_b_id,
        "headers_a1": {"Authorization": f"Bearer {key_a1}"},
        "headers_a2": {"Authorization": f"Bearer {key_a2}"},
        "headers_b": {"Authorization": f"Bearer {key_b}"},
    }


@pytest.mark.asyncio
async def test_cross_tenant_semantic_isolation(async_client: AsyncClient):
    with (
        patch.object(settings, "semantic_cache_enabled", True),
        patch.object(settings, "semantic_cache_threshold", 0.85),
    ):
        t1 = await create_tenant_hierarchy(async_client, "TenantOne")
        t2 = await create_tenant_hierarchy(async_client, "TenantTwo")

        # Tenant 1 sends Request 1
        resp1 = await async_client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": "How does TCP congestion control work?"}],
            },
            headers=t1["headers_a1"],
        )
        assert resp1.status_code == 200
        assert resp1.headers.get("X-Tollgate-Cache") == "MISS"

        # Tenant 2 sends semantically equivalent Request
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
            headers=t2["headers_a1"],
        )
        assert resp2.status_code == 200
        # Tenant 2 must NOT receive a semantic hit from Tenant 1
        assert resp2.headers.get("X-Tollgate-Cache") == "MISS"


@pytest.mark.asyncio
async def test_cross_project_semantic_isolation(async_client: AsyncClient):
    with (
        patch.object(settings, "semantic_cache_enabled", True),
        patch.object(settings, "semantic_cache_threshold", 0.85),
    ):
        t = await create_tenant_hierarchy(async_client, "CrossProj")

        # Project A sends Request 1
        resp_a = await async_client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": "How does TCP congestion control work?"}],
            },
            headers=t["headers_a1"],
        )
        assert resp_a.status_code == 200
        assert resp_a.headers.get("X-Tollgate-Cache") == "MISS"

        # Project B (same tenant) sends semantically equivalent request
        resp_b = await async_client.post(
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
            headers=t["headers_b"],
        )
        assert resp_b.status_code == 200
        # Project B must NOT receive Project A's semantic cache hit
        assert resp_b.headers.get("X-Tollgate-Cache") == "MISS"


@pytest.mark.asyncio
async def test_intra_project_api_keys_share_semantic_cache(async_client: AsyncClient):
    with (
        patch.object(settings, "semantic_cache_enabled", True),
        patch.object(settings, "semantic_cache_threshold", 0.85),
    ):
        t = await create_tenant_hierarchy(async_client, "SharedKey")

        # Key A1 warms semantic cache
        resp1 = await async_client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": "How does TCP congestion control work?"}],
            },
            headers=t["headers_a1"],
        )
        assert resp1.status_code == 200
        assert resp1.headers.get("X-Tollgate-Cache") == "MISS"

        # Key A2 (same project) sends semantically similar prompt
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
            headers=t["headers_a2"],
        )
        assert resp2.status_code == 200
        # Key A2 within same project receives SEMANTIC_HIT
        assert resp2.headers.get("X-Tollgate-Cache") == "SEMANTIC_HIT"


@pytest.mark.asyncio
async def test_model_isolation_in_semantic_cache(async_client: AsyncClient):
    with (
        patch.object(settings, "semantic_cache_enabled", True),
        patch.object(settings, "semantic_cache_threshold", 0.85),
    ):
        t = await create_tenant_hierarchy(async_client, "ModelIso")

        # gpt-4o request warms cache
        resp1 = await async_client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": "How does TCP congestion control work?"}],
            },
            headers=t["headers_a1"],
        )
        assert resp1.status_code == 200
        assert resp1.headers.get("X-Tollgate-Cache") == "MISS"

        # Same project sends similar request with gpt-4o-mini
        resp2 = await async_client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-fast",
                "messages": [
                    {
                        "role": "user",
                        "content": "Can you explain the mechanism behind TCP congestion control?",
                    }
                ],
            },
            headers=t["headers_a1"],
        )
        assert resp2.status_code == 200
        # Different model must NOT receive semantic hit
        assert resp2.headers.get("X-Tollgate-Cache") == "MISS"
