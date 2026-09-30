import uuid

import pytest
from gateway.src.budgets.manager import BudgetLimits, budget_manager
from gateway.src.cache.service import ExactResponseCache, InMemoryCacheBackend
from gateway.src.db import get_db
from gateway.src.main import app
from gateway.src.ratelimit.limiter import InMemoryRateLimitBackend, RateLimiter
from gateway.src.schemas.api_key import APIKeyCreate
from gateway.src.schemas.chat import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    UsageInfo,
)
from gateway.src.services.api_key_service import create_api_key
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.models import Project, Tenant, User
from tollgate_core.security import hash_password

from tests.conftest import TestAsyncSessionLocal


@pytest.mark.asyncio
async def test_multi_instance_cross_tenant_isolation(db_session: AsyncSession):
    """
    Verifies that when multiple API instances run concurrently:
    1. Tenant A cannot authenticate or access Tenant B's data on either instance.
    2. Tenant A and Tenant B have completely isolated rate-limiting buckets.
    3. Tenant A and Tenant B have strictly isolated budget allocations.
    4. Exact cache entries for Tenant A are inaccessible to Tenant B across instances.
    """
    # 1. Setup Tenant A and Tenant B
    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()
    project_a_id = uuid.uuid4()
    project_b_id = uuid.uuid4()
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()

    tenant_a = Tenant(id=tenant_a_id, name="Tenant Alpha", slug=f"alpha-{uuid.uuid4().hex[:6]}")
    tenant_b = Tenant(id=tenant_b_id, name="Tenant Beta", slug=f"beta-{uuid.uuid4().hex[:6]}")
    project_a = Project(
        id=project_a_id, tenant_id=tenant_a_id, name="Project Alpha", slug="proj-alpha"
    )
    project_b = Project(
        id=project_b_id, tenant_id=tenant_b_id, name="Project Beta", slug="proj-beta"
    )
    user_a = User(
        id=user_a_id,
        tenant_id=tenant_a_id,
        email="user_a@alpha.com",
        name="User Alpha",
        password_hash=hash_password("PassA123!"),
        role="admin",
        status="active",
    )
    user_b = User(
        id=user_b_id,
        tenant_id=tenant_b_id,
        email="user_b@beta.com",
        name="User Beta",
        password_hash=hash_password("PassB123!"),
        role="admin",
        status="active",
    )
    db_session.add_all([tenant_a, tenant_b, project_a, project_b, user_a, user_b])
    await db_session.commit()

    # Create API keys for both tenants
    key_a = (
        await create_api_key(
            db_session, project_a_id, tenant_a_id, APIKeyCreate(name="Key A", user_id=user_a_id)
        )
    ).key
    key_b = (
        await create_api_key(
            db_session, project_b_id, tenant_b_id, APIKeyCreate(name="Key B", user_id=user_b_id)
        )
    ).key

    # 2. Verify API and Dashboard isolation across two gateway instances
    async def _override_get_db():
        async with TestAsyncSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        transport_1 = ASGITransport(app=app)
        transport_2 = ASGITransport(app=app)

        async with (
            AsyncClient(transport=transport_1, base_url="http://gateway-1:8000") as client_1,
            AsyncClient(transport=transport_2, base_url="http://gateway-2:8000") as client_2,
        ):

            # Instance 1 checks Tenant A
            res_a1 = await client_1.get(
                "/api/v1/dashboard/me", headers={"Authorization": f"Bearer {key_a}"}
            )
            assert res_a1.status_code == 200
            assert res_a1.json()["tenant_id"] == str(tenant_a_id)

            # Instance 2 checks Tenant B
            res_b2 = await client_2.get(
                "/api/v1/dashboard/me", headers={"Authorization": f"Bearer {key_b}"}
            )
            assert res_b2.status_code == 200
            assert res_b2.json()["tenant_id"] == str(tenant_b_id)

            # Cross-tenant query attempt: Tenant A cannot view Tenant B's projects
            res_cross = await client_1.get(
                f"/api/v1/dashboard/overview?project_id={project_b_id}",
                headers={"Authorization": f"Bearer {key_a}"},
            )
            assert res_cross.status_code in (403, 404)
    finally:
        app.dependency_overrides.clear()

    # 3. Verify Rate Limiting Isolation across instances
    shared_rate_backend = InMemoryRateLimitBackend()
    limiter = RateLimiter(backend=shared_rate_backend, burst=2, requests_per_second=1.0)

    # Exhaust Tenant A's tokens
    res_a_1 = await limiter.check(tenant_id=tenant_a_id, cost=1)
    res_a_2 = await limiter.check(tenant_id=tenant_a_id, cost=1)
    res_a_3 = await limiter.check(tenant_id=tenant_a_id, cost=1)
    assert res_a_1.allowed is True
    assert res_a_2.allowed is True
    assert res_a_3.allowed is False  # Rate limited

    # Tenant B must NOT be affected by Tenant A's exhausted quota
    res_b_1 = await limiter.check(tenant_id=tenant_b_id, cost=1)
    assert res_b_1.allowed is True

    # 4. Verify Budget Isolation across instances
    limits_a = BudgetLimits(tenant_daily_limit=3000, tenant_monthly_limit=30000)
    limits_b = BudgetLimits(tenant_daily_limit=5000, tenant_monthly_limit=50000)

    res_res_a = await budget_manager.reserve(tenant_a_id, project_a_id, 3000, limits_a)
    assert res_res_a.allowed is True

    # Tenant A is now at capacity
    res_res_a_over = await budget_manager.reserve(tenant_a_id, project_a_id, 100, limits_a)
    assert res_res_a_over.allowed is False

    # Tenant B has full capacity remaining
    res_res_b = await budget_manager.reserve(tenant_b_id, project_b_id, 4000, limits_b)
    assert res_res_b.allowed is True

    # 5. Verify Cache Isolation across instances
    cache_backend = InMemoryCacheBackend()
    cache_inst_1 = ExactResponseCache(backend=cache_backend)
    cache_inst_2 = ExactResponseCache(backend=cache_backend)

    shared_prompt = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="Classified company query")],
    )
    resp_a = ChatCompletionResponse(
        id="chatcmpl-a-1",
        created=1711800000,
        model="gpt-4o",
        choices=[
            ChatChoice(
                index=0,
                message=ChatChoiceMessage(role="assistant", content="Confidential Alpha data"),
            )
        ],
        usage=UsageInfo(prompt_tokens=5, completion_tokens=5, total_tokens=10),
    )

    # Store for Tenant A on Instance 1
    await cache_inst_1.set(shared_prompt, resp_a, tenant_a_id, project_a_id, "openai")

    # Instance 2 query by Tenant B for identical prompt must MISS
    cached_b = await cache_inst_2.get(shared_prompt, tenant_b_id, project_b_id, "openai")
    assert cached_b is None

    # Instance 2 query by Tenant A hits
    cached_a = await cache_inst_2.get(shared_prompt, tenant_a_id, project_a_id, "openai")
    assert cached_a is not None
    assert cached_a.choices[0].message.content == "Confidential Alpha data"
