"""Tests for Cache & Router Analytics Endpoints."""

import uuid
from datetime import datetime, timezone

import pytest
from gateway.src.cache import exact_cache
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import SemanticCacheEntry
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.persistence import persist_usage_event


@pytest.fixture
async def setup_cache_router_data(async_client: AsyncClient, db_session: AsyncSession):
    t_res = await async_client.post(
        "/api/v1/tenants",
        json={"name": "CacheRouter Corp", "slug": f"cr-{uuid.uuid4().hex[:6]}"},
    )
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "CR Project", "slug": f"cr-p-{uuid.uuid4().hex[:6]}"},
    )
    project_id = p_res.json()["id"]

    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "CR Key"}
    )
    admin_key = k_res.json()["key"]

    t_uuid = uuid.UUID(tenant_id)
    p_uuid = uuid.UUID(project_id)

    # 1. Record Exact Cache Hits and Misses
    await exact_cache.record_tenant_hit(t_uuid, p_uuid)
    await exact_cache.record_tenant_hit(t_uuid, p_uuid)
    await exact_cache.record_tenant_miss(t_uuid, p_uuid)

    # 2. Add Semantic Cache Entry with hit_count=3
    sem_entry = SemanticCacheEntry(
        id=uuid.uuid4(),
        tenant_id=t_uuid,
        project_id=p_uuid,
        provider="openai",
        model="gpt-4o",
        request_fingerprint="fp_123",
        embedding=[0.0] * 1536,
        embedding_model="text-embedding-3-small",
        embedding_version="v1",
        response_cache_key="key_123",
        expires_at=datetime.now(timezone.utc),
        hit_count=3,
    )
    db_session.add(sem_entry)

    # 3. Seed Router Usage Events: 3 cheap, 1 strong
    for i in range(4):
        route = "cheap" if i < 3 else "strong"
        ev = UsageEventPayload(
            request_id=f"req_cr_{i}",
            tenant_id=t_uuid,
            project_id=p_uuid,
            provider="openai",
            model="mock-fast" if route == "cheap" else "mock-model",
            status="success",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            actual_cost=200_000,
            router_mode="learned",
            router_route=route,
            router_confidence=0.85,
            router_fallback=False,
        )
        await persist_usage_event(db_session, ev)

    await db_session.commit()

    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "headers": {"Authorization": f"Bearer {admin_key}"},
    }


@pytest.mark.asyncio
async def test_cache_analytics_endpoint(async_client: AsyncClient, setup_cache_router_data):
    """Verify cache analytics aggregation."""
    headers = setup_cache_router_data["headers"]

    res = await async_client.get("/api/v1/dashboard/cache", headers=headers)
    assert res.status_code == 200
    cache = res.json()

    assert cache["exact_hits"] >= 2
    assert cache["semantic_hits"] >= 3
    assert cache["total_cache_hits"] >= 5
    assert cache["semantic_entries_count"] >= 1
    assert cache["estimated_calls_avoided"] >= 5
    assert cache["overall_hit_rate"] > 0.0


@pytest.mark.asyncio
async def test_router_analytics_endpoint(async_client: AsyncClient, setup_cache_router_data):
    """Verify router analytics: selections, percentages, and offline evaluation inclusion."""
    headers = setup_cache_router_data["headers"]

    res = await async_client.get("/api/v1/dashboard/router?range=24h", headers=headers)
    assert res.status_code == 200
    router = res.json()

    assert router["cheap_selections"] == 3
    assert router["strong_selections"] == 1
    assert router["cheap_percentage"] == 75.0
    assert router["strong_percentage"] == 25.0
    assert router["avg_confidence"] > 0.0

    # Offline evaluation report loaded from disk
    assert router["offline_evaluation"] is not None
    assert "baselines" in router["offline_evaluation"]
    assert "always_cheap" in router["offline_evaluation"]["baselines"]
    assert "always_strong" in router["offline_evaluation"]["baselines"]
