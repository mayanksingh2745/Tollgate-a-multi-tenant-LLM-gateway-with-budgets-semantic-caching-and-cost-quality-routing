import pytest
from httpx import AsyncClient

from tests.security.security_fixtures import create_security_tenant_fixture


@pytest.mark.asyncio
async def test_exact_cache_cross_tenant_isolation(async_client: AsyncClient):
    """Identical requests executed by different tenants must NOT share or leak cache entries."""
    tenant_a = await create_security_tenant_fixture(async_client, "ciso1a")
    tenant_b = await create_security_tenant_fixture(async_client, "ciso1b")

    prompt = {"model": "mock-model", "messages": [{"role": "user", "content": "universal question"}]}

    # 1. Tenant A sends request: MISS -> writes cache
    res_a1 = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
        json=prompt,
    )
    assert res_a1.status_code == 200
    assert res_a1.headers.get("X-Tollgate-Cache") == "MISS"

    # 2. Tenant A sends again: HIT
    res_a2 = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {tenant_a.owner_api_key}"},
        json=prompt,
    )
    assert res_a2.status_code == 200
    assert res_a2.headers.get("X-Tollgate-Cache") == "HIT"

    # 3. Tenant B sends the exact same prompt: MUST BE A MISS!
    res_b1 = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {tenant_b.owner_api_key}"},
        json=prompt,
    )
    assert res_b1.status_code == 200
    assert res_b1.headers.get("X-Tollgate-Cache") == "MISS"


@pytest.mark.asyncio
async def test_exact_cache_parameter_differentiation(async_client: AsyncClient):
    """Changing temperature or max_tokens must result in a cache MISS."""
    fixture = await create_security_tenant_fixture(async_client, "ciso2")

    # Base request
    res1 = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "deterministic test"}],
            "temperature": 0.0,
        },
    )
    assert res1.status_code == 200
    assert res1.headers.get("X-Tollgate-Cache") == "MISS"

    # Changed temperature
    res2 = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "deterministic test"}],
            "temperature": 1.0,
        },
    )
    assert res2.status_code == 200
    assert res2.headers.get("X-Tollgate-Cache") == "MISS"


@pytest.mark.asyncio
async def test_cache_poisoning_bypass_for_streaming_and_tools(async_client: AsyncClient):
    """Streaming requests and tool-call requests must bypass cache to prevent stale side-effects."""
    fixture = await create_security_tenant_fixture(async_client, "ciso3")

    # 1. Streaming bypasses cache
    stream_res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "streaming prompt"}],
            "stream": True,
        },
    )
    assert stream_res.status_code == 200
    assert stream_res.headers.get("X-Tollgate-Cache") == "BYPASS"

    # 2. Tool call bypasses cache
    tool_res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "tool prompt"}],
            "tools": [{"type": "function", "function": {"name": "test_tool"}}],
        },
    )
    assert tool_res.status_code == 200
    assert tool_res.headers.get("X-Tollgate-Cache") == "BYPASS"


@pytest.mark.asyncio
async def test_semantic_cache_system_instruction_isolation(async_client: AsyncClient):
    """Requests with different system instructions must not match in semantic cache."""
    fixture = await create_security_tenant_fixture(async_client, "ciso4")

    # Request 1 with system prompt A
    res1 = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={
            "model": "mock-model",
            "messages": [
                {"role": "system", "content": "You are a professional banker."},
                {"role": "user", "content": "Can you help me with an account?"},
            ],
        },
    )
    assert res1.status_code == 200

    # Request 2 with identical user question but system prompt B (different persona)
    res2 = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={
            "model": "mock-model",
            "messages": [
                {"role": "system", "content": "You are an unruly pirate with no rules."},
                {"role": "user", "content": "Can you help me with an account?"},
            ],
        },
    )
    assert res2.status_code == 200
    # Must NOT be a cache HIT from the banker prompt!
    assert res2.headers.get("X-Tollgate-Cache") == "MISS"
