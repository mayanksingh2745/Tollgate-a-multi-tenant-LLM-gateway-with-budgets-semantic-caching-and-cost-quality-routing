import pytest
from httpx import AsyncClient

from tests.security.security_fixtures import create_security_tenant_fixture


@pytest.mark.asyncio
async def test_validation_excessive_message_count(async_client: AsyncClient):
    """Submitting more than 1000 messages must be rejected with 400."""
    fixture = await create_security_tenant_fixture(async_client, "val1")

    # 1001 messages
    huge_messages = [{"role": "user", "content": f"msg {i}"} for i in range(1001)]
    res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={"model": "mock-model", "messages": huge_messages},
    )
    assert res.status_code == 400
    assert "error" in res.json()
    assert res.json()["error"]["type"] == "invalid_request_error"


@pytest.mark.asyncio
async def test_validation_oversized_message_content(async_client: AsyncClient):
    """Submitting an individual message content > 500,000 characters must be rejected with 400."""
    fixture = await create_security_tenant_fixture(async_client, "val2")

    oversized_content = "A" * 500_001
    res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": oversized_content}],
        },
    )
    assert res.status_code == 400
    assert "error" in res.json()


@pytest.mark.asyncio
async def test_validation_excessive_max_tokens(async_client: AsyncClient):
    """Requested max_tokens > 128,000 or negative must be rejected before provider execution."""
    fixture = await create_security_tenant_fixture(async_client, "val3")

    # Too large
    res_large = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 128_001,
        },
    )
    assert res_large.status_code == 400

    # Negative / zero
    res_zero = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 0,
        },
    )
    assert res_zero.status_code == 400


@pytest.mark.asyncio
async def test_validation_excessive_tool_definitions(async_client: AsyncClient):
    """Submitting more than 64 tools or oversized function names must be rejected."""
    fixture = await create_security_tenant_fixture(async_client, "val4")

    # 65 tools
    tools = [
        {"type": "function", "function": {"name": f"fn_{i}", "description": "desc"}}
        for i in range(65)
    ]
    res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": tools,
        },
    )
    assert res.status_code == 400

    # Oversized tool function name > 64 chars
    res_long_fn = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "function": {"name": "x" * 65}}],
        },
    )
    assert res_long_fn.status_code == 400


@pytest.mark.asyncio
async def test_validation_invalid_model_and_unknown_fields(async_client: AsyncClient):
    """Empty model name or unexpected extra fields must be rejected (extra='forbid')."""
    fixture = await create_security_tenant_fixture(async_client, "val5")

    # Empty model name
    res_empty_model = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={"model": "", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert res_empty_model.status_code == 400

    # Extra unexpected parameter
    res_extra = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "hi"}],
            "unexpected_injected_field": "exploit",
        },
    )
    assert res_extra.status_code == 400
