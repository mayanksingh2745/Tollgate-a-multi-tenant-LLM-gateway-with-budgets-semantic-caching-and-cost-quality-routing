import pytest
from httpx import AsyncClient

from tests.security.security_fixtures import create_security_tenant_fixture


@pytest.mark.asyncio
async def test_sql_injection_dashboard_search(async_client: AsyncClient):
    """Malicious SQL syntax in dashboard search must be safely parameterized without syntax errors."""
    fixture = await create_security_tenant_fixture(async_client, "sqli1")

    payloads = [
        "' OR '1'='1",
        "'; DROP TABLE usage_events; --",
        "' UNION SELECT id, name, slug FROM projects --",
        '" OR ""="',
        "admin'--",
        "\\'; EXEC xp_cmdshell('dir');--",
    ]

    for p in payloads:
        res = await async_client.get(
            f"/api/v1/dashboard/requests?search={p}",
            headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        )
        assert res.status_code == 200, f"Failed for search payload: {p}"
        data = res.json()
        assert "items" in data
        assert "total" in data


@pytest.mark.asyncio
async def test_sql_injection_dashboard_sorting(async_client: AsyncClient):
    """Malicious SQL syntax in sort_by or sort_order must fall back safely to whitelisted columns."""
    fixture = await create_security_tenant_fixture(async_client, "sqli2")

    payloads = [
        "created_at; DROP TABLE tenants;--",
        "(SELECT CASE WHEN (1=1) THEN created_at ELSE NULL END)",
        "actual_cost DESC, (SELECT 1 FROM pg_sleep(5))",
        "' OR 1=1 --",
    ]

    for p in payloads:
        res = await async_client.get(
            f"/api/v1/dashboard/requests?sort_by={p}&sort_order=desc",
            headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        )
        assert res.status_code == 200, f"Failed for sort_by payload: {p}"
        data = res.json()
        assert "items" in data


@pytest.mark.asyncio
async def test_sql_injection_dashboard_filters(async_client: AsyncClient):
    """Malicious SQL syntax in model, provider, or status filters must be safely parameterized."""
    fixture = await create_security_tenant_fixture(async_client, "sqli3")

    payloads = [
        "' OR 1=1 --",
        "gpt-4o' UNION SELECT * FROM users --",
        "openai'; DELETE FROM projects; --",
    ]

    for p in payloads:
        res = await async_client.get(
            f"/api/v1/dashboard/requests?model={p}&provider={p}&status={p}",
            headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        assert data["total"] == 0
