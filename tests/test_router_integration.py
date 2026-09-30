"""Integration tests for Learned Model Router gateway request flow."""

from pathlib import Path

import pytest
from gateway.src.config import settings
from gateway.src.router import model_router
from httpx import AsyncClient

ROOT_DIR = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = str(ROOT_DIR / "artifacts" / "router")


@pytest.fixture
async def setup_tenant_and_key(async_client: AsyncClient):
    """Helper fixture to create a valid tenant, project, and API key."""
    t_res = await async_client.post(
        "/api/v1/tenants", json={"name": "Router Test Co", "slug": "router-test-co"}
    )
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "Router Project", "slug": "router-proj"},
    )
    project_id = p_res.json()["id"]

    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "Router Key"}
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
async def test_router_disabled_by_default(async_client: AsyncClient, setup_tenant_and_key):
    """When router is disabled (default), requests pass through unmodified."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello there"}],
    }
    res = await async_client.post(
        "/v1/chat/completions",
        headers=setup_tenant_and_key["headers"],
        json=payload,
    )
    assert res.status_code == 200
    assert "X-Tollgate-Router-Route" not in res.headers
    data = res.json()
    assert data["model"].startswith("mock-model")


@pytest.mark.asyncio
async def test_static_router_mode(async_client: AsyncClient, setup_tenant_and_key):
    """Static router forces selection to configured target model."""
    settings.router_enabled = True
    settings.router_mode = "static"
    settings.router_strong_model = "mock-fast"
    model_router.initialize()

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Explain gravity in one sentence"}],
    }
    res = await async_client.post(
        "/v1/chat/completions",
        headers=setup_tenant_and_key["headers"],
        json=payload,
    )
    assert res.status_code == 200
    assert res.headers["X-Tollgate-Router-Route"] == "static"
    assert res.headers["X-Tollgate-Router-Selected-Model"] == "mock-fast"


@pytest.mark.asyncio
async def test_learned_router_simple_query_routes_to_cheap(
    async_client: AsyncClient, setup_tenant_and_key
):
    """Learned router routes simple factual queries to cheap model."""
    settings.router_enabled = True
    settings.router_mode = "learned"
    settings.router_artifact_path = ARTIFACT_PATH
    settings.router_quality_threshold = 0.7
    settings.router_cheap_model = "mock-fast"
    settings.router_strong_model = "mock-model"
    model_router.initialize()

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "What is the capital of Spain?"}],
    }
    res = await async_client.post(
        "/v1/chat/completions",
        headers=setup_tenant_and_key["headers"],
        json=payload,
    )
    assert res.status_code == 200
    assert res.headers.get("X-Tollgate-Router-Route") == "cheap"
    assert res.headers.get("X-Tollgate-Router-Selected-Model") == "mock-fast"
    assert float(res.headers.get("X-Tollgate-Router-Confidence", 0)) >= 0.7


@pytest.mark.asyncio
async def test_learned_router_complex_query_routes_to_strong(
    async_client: AsyncClient, setup_tenant_and_key
):
    """Learned router routes complex SQL/reasoning queries to strong model."""
    settings.router_enabled = True
    settings.router_mode = "learned"
    settings.router_artifact_path = ARTIFACT_PATH
    settings.router_quality_threshold = 0.7
    settings.router_cheap_model = "mock-fast"
    settings.router_strong_model = "mock-model"
    model_router.initialize()

    content = (
        "Write a complex PostgreSQL query with CTEs to calculate 30-day customer churn:\n"
        "SELECT customer_id, signup_date FROM subscriptions WHERE status = 'active' "
        "GROUP BY customer_id ORDER BY signup_date DESC;"
    )
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": content}],
    }
    res = await async_client.post(
        "/v1/chat/completions",
        headers=setup_tenant_and_key["headers"],
        json=payload,
    )
    assert res.status_code == 200
    assert res.headers.get("X-Tollgate-Router-Route") == "strong"
    assert res.headers.get("X-Tollgate-Router-Selected-Model") == "mock-model"


@pytest.mark.asyncio
async def test_learned_router_shadow_mode(async_client: AsyncClient, setup_tenant_and_key):
    """In shadow mode, router calculates route but does not modify request model."""
    settings.router_enabled = True
    settings.router_mode = "learned"
    settings.router_shadow_mode = True
    settings.router_artifact_path = ARTIFACT_PATH
    settings.router_cheap_model = "mock-fast"
    settings.router_strong_model = "mock-model"
    model_router.initialize()

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "What color is the sky?"}],
    }
    res = await async_client.post(
        "/v1/chat/completions",
        headers=setup_tenant_and_key["headers"],
        json=payload,
    )
    assert res.status_code == 200
    assert res.headers.get("X-Tollgate-Router-Shadow") == "true"
    assert res.headers.get("X-Tollgate-Router-Route") == "cheap"
    data = res.json()
    # Provider was called with original model mock-model
    assert data["model"].startswith("mock-model")


@pytest.mark.asyncio
async def test_cache_hit_bypasses_router(async_client: AsyncClient, setup_tenant_and_key):
    """Exact cache hits return prior responses without re-routing."""
    settings.router_enabled = True
    settings.router_mode = "static"
    settings.router_strong_model = "mock-fast"
    model_router.initialize()

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Identical cache test message"}],
    }

    # First request: Cache MISS -> Router executes
    res1 = await async_client.post(
        "/v1/chat/completions",
        headers=setup_tenant_and_key["headers"],
        json=payload,
    )
    assert res1.status_code == 200
    assert res1.headers.get("X-Tollgate-Cache") == "MISS"
    assert res1.headers.get("X-Tollgate-Router-Route") == "static"

    # Second request: Cache HIT -> returns cached response
    res2 = await async_client.post(
        "/v1/chat/completions",
        headers=setup_tenant_and_key["headers"],
        json=payload,
    )
    assert res2.status_code == 200
    assert res2.headers.get("X-Tollgate-Cache") == "HIT"


@pytest.mark.asyncio
async def test_router_fail_open_on_missing_artifact(
    async_client: AsyncClient, setup_tenant_and_key
):
    """When router fails to load artifact, it fails open without breaking requests."""
    settings.router_enabled = True
    settings.router_mode = "learned"
    settings.router_artifact_path = "/non_existent/path"
    model_router.initialize()

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    res = await async_client.post(
        "/v1/chat/completions",
        headers=setup_tenant_and_key["headers"],
        json=payload,
    )
    assert res.status_code == 200
    assert res.json()["model"].startswith("mock-model")
