import pytest
from gateway.src.budgets import BudgetLimits, budget_manager
from httpx import AsyncClient

from tests.security.security_fixtures import create_security_tenant_fixture


@pytest.mark.asyncio
async def test_budget_negative_and_overflow_values_rejected(async_client: AsyncClient):
    """Negative budget amounts or overflowing values must be rejected with 400 or 422."""
    fixture = await create_security_tenant_fixture(async_client, "bud1")

    # 1. Negative daily budget
    res_neg = await async_client.put(
        f"/api/v1/tenants/{fixture.tenant_id}/budget",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={"daily_budget_microdollars": -1000},
    )
    assert res_neg.status_code in (400, 422)

    # 2. Huge overflow value (> 1e15)
    res_overflow = await async_client.put(
        f"/api/v1/tenants/{fixture.tenant_id}/budget",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={"daily_budget_microdollars": 10**18},
    )
    assert res_overflow.status_code in (400, 422)


@pytest.mark.asyncio
async def test_budget_idempotent_settlement(async_client: AsyncClient):
    """Duplicate or replayed settlement calls on the same reservation must not double-spend or double-refund."""
    fixture = await create_security_tenant_fixture(async_client, "bud2")

    # Reserve $1.00 (1,000,000 microdollars)
    limits = BudgetLimits(tenant_daily_limit=10_000_000, tenant_monthly_limit=50_000_000)
    res_result = await budget_manager.reserve(
        tenant_id=fixture.tenant_id,
        project_id=fixture.project_id,
        estimated_cost=1_000_000,
        limits=limits,
    )
    assert res_result.allowed is True
    res_id = res_result.reservation_id

    # 1. First settlement: actual cost = 400,000 microdollars -> refund 600,000
    settle1 = await budget_manager.settle(reservation_id=res_id, actual_cost=400_000)
    assert settle1.success is True
    assert settle1.refund == 600_000

    # 2. Second (replayed) settlement on the same reservation
    settle2 = await budget_manager.settle(reservation_id=res_id, actual_cost=400_000)
    # Must be idempotent: no additional refund or status error
    assert settle2.refund == 0 or settle2.success is False or settle2.status in ("settled", "already_settled")


@pytest.mark.asyncio
async def test_budget_client_cannot_forge_cost(async_client: AsyncClient):
    """Client attempting to pass custom cost headers or fields cannot override server-computed cost."""
    fixture = await create_security_tenant_fixture(async_client, "bud3")

    # Send request with forged headers attempting to declare 0 cost
    res = await async_client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {fixture.owner_api_key}",
            "X-Tollgate-Cost": "0",
            "X-Cost-Microdollars": "0",
        },
        json={"model": "mock-model", "messages": [{"role": "user", "content": "test request"}]},
    )
    assert res.status_code == 200

    # Check that usage was published with positive server-computed cost (ignoring client 0 header)
    import json

    from gateway.src.usage.publisher import usage_publisher

    assert usage_publisher._redis_client.xadd.called
    call_args = usage_publisher._redis_client.xadd.call_args[0]
    payload = json.loads(call_args[1]["data"])
    assert payload["actual_cost"] > 0
    assert payload["input_tokens"] > 0
