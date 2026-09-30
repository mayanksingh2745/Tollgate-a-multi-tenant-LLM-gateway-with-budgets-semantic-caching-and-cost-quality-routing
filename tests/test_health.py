import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_endpoint(async_client: AsyncClient):
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Tollgate LLM Gateway"
    assert data["status"] == "online"


@pytest.mark.asyncio
async def test_healthz_endpoint(async_client: AsyncClient):
    response = await async_client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_livez_endpoint(async_client: AsyncClient):
    response = await async_client.get("/livez")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"

    # Also test /health/live alias
    alias_resp = await async_client.get("/health/live")
    assert alias_resp.status_code == 200
    assert alias_resp.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_version_endpoint(async_client: AsyncClient):
    response = await async_client.get("/health/version")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "tollgate-api"
    assert "version" in data
    assert "git_commit" in data
    assert "environment" in data

    # Test alias
    alias_resp = await async_client.get("/version")
    assert alias_resp.status_code == 200
    assert alias_resp.json()["service"] == "tollgate-api"
