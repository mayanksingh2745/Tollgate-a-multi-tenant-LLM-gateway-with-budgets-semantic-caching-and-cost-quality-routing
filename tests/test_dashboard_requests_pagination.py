"""Tests for Requests Explorer, Server-Side Pagination, Filtering, Sorting, and Detail View."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.usage import UsageEventPayload

from apps.worker.src.persistence import persist_usage_event


@pytest.fixture
async def setup_requests_data(async_client: AsyncClient, db_session: AsyncSession):
    t_res = await async_client.post(
        "/api/v1/tenants",
        json={"name": "Req Corp", "slug": f"req-{uuid.uuid4().hex[:6]}"},
    )
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "Production API", "slug": f"prod-{uuid.uuid4().hex[:6]}"},
    )
    project_id = p_res.json()["id"]

    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "Admin Key"}
    )
    admin_key = k_res.json()["key"]

    now = datetime.now(timezone.utc)

    # Seed 15 deterministic requests
    for i in range(15):
        ev = UsageEventPayload(
            request_id=f"req_test_{i:03d}",
            tenant_id=uuid.UUID(tenant_id),
            project_id=uuid.UUID(project_id),
            provider="openai" if i % 2 == 0 else "anthropic",
            model="gpt-4o" if i % 2 == 0 else "claude-3-haiku",
            status="success" if i != 5 else "provider_failure",
            input_tokens=100 + i * 10,
            output_tokens=50 + i * 5,
            total_tokens=150 + i * 15,
            actual_cost=(i + 1) * 100_000,
            latency_ms=100.0 + i * 20.0,
            router_route="cheap" if i % 3 == 0 else "strong",
            cache_status="MISS",
            timestamp=now - timedelta(minutes=i * 5),
        )
        await persist_usage_event(db_session, ev)

    await db_session.commit()

    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "headers": {"Authorization": f"Bearer {admin_key}"},
    }


@pytest.mark.asyncio
async def test_pagination_pages_and_sizes(async_client: AsyncClient, setup_requests_data):
    """Test pagination bounds and page sizes."""
    headers = setup_requests_data["headers"]

    # Page 1 with page_size=5 -> 5 items, total=15, total_pages=3
    res1 = await async_client.get("/api/v1/dashboard/requests?page=1&page_size=5", headers=headers)
    assert res1.status_code == 200
    p1 = res1.json()
    assert len(p1["items"]) == 5
    assert p1["total"] == 15
    assert p1["page"] == 1
    assert p1["page_size"] == 5
    assert p1["total_pages"] == 3

    # Page 2 with page_size=5
    res2 = await async_client.get("/api/v1/dashboard/requests?page=2&page_size=5", headers=headers)
    assert res2.status_code == 200
    p2 = res2.json()
    assert len(p2["items"]) == 5
    assert p2["page"] == 2
    # Ensure distinct items across pages
    ids_p1 = {item["request_id"] for item in p1["items"]}
    ids_p2 = {item["request_id"] for item in p2["items"]}
    assert ids_p1.isdisjoint(ids_p2)

    # Empty Page beyond total
    res4 = await async_client.get("/api/v1/dashboard/requests?page=4&page_size=5", headers=headers)
    assert res4.status_code == 200
    assert len(res4.json()["items"]) == 0


@pytest.mark.asyncio
async def test_filtering(async_client: AsyncClient, setup_requests_data):
    """Test filtering by provider, status, model, and search string."""
    headers = setup_requests_data["headers"]

    # Filter by provider: openai
    res_prov = await async_client.get(
        "/api/v1/dashboard/requests?provider=openai&page_size=50", headers=headers
    )
    assert res_prov.status_code == 200
    items_prov = res_prov.json()["items"]
    assert len(items_prov) == 8
    assert all(it["provider"] == "openai" for it in items_prov)

    # Filter by failure status
    res_fail = await async_client.get(
        "/api/v1/dashboard/requests?status=provider_failure", headers=headers
    )
    assert res_fail.status_code == 200
    items_fail = res_fail.json()["items"]
    assert len(items_fail) == 1
    assert items_fail[0]["request_id"] == "req_test_005"

    # Search by partial request_id
    res_search = await async_client.get("/api/v1/dashboard/requests?search=012", headers=headers)
    assert res_search.status_code == 200
    assert len(res_search.json()["items"]) == 1
    assert res_search.json()["items"][0]["request_id"] == "req_test_012"


@pytest.mark.asyncio
async def test_safe_sorting(async_client: AsyncClient, setup_requests_data):
    """Test sorting by actual_cost and latency_ms in asc/desc order."""
    headers = setup_requests_data["headers"]

    # Sort by actual_cost asc
    res_cost_asc = await async_client.get(
        "/api/v1/dashboard/requests?sort_by=actual_cost&sort_order=asc&page_size=15",
        headers=headers,
    )
    items_cost = res_cost_asc.json()["items"]
    costs = [it["actual_cost_microdollars"] for it in items_cost]
    assert costs == sorted(costs)

    # Sort by latency_ms desc
    res_lat_desc = await async_client.get(
        "/api/v1/dashboard/requests?sort_by=latency_ms&sort_order=desc&page_size=15",
        headers=headers,
    )
    items_lat = res_lat_desc.json()["items"]
    latencies = [it["latency_ms"] for it in items_lat]
    assert latencies == sorted(latencies, reverse=True)


@pytest.mark.asyncio
async def test_request_detail_safe_metadata(async_client: AsyncClient, setup_requests_data):
    """Verify request detail endpoint returns safe metadata and omits secret/raw data."""
    headers = setup_requests_data["headers"]

    res = await async_client.get("/api/v1/dashboard/requests/req_test_000", headers=headers)
    assert res.status_code == 200
    detail = res.json()

    assert detail["request_id"] == "req_test_000"
    assert detail["project_name"] == "Production API"
    assert detail["model"] == "gpt-4o"
    assert detail["provider"] == "openai"
    assert detail["status"] == "success"
    assert detail["total_tokens"] == 150
    assert detail["actual_cost_microdollars"] == 100_000

    # Ensure no secrets or raw prompt/response keys in response schema
    assert "prompt" not in detail
    assert "messages" not in detail
    assert "response" not in detail
    assert "choices" not in detail
    assert "api_key" not in detail
    assert "authorization" not in detail

    # 404 on nonexistent request
    res_404 = await async_client.get("/api/v1/dashboard/requests/nonexistent_req", headers=headers)
    assert res_404.status_code == 404
