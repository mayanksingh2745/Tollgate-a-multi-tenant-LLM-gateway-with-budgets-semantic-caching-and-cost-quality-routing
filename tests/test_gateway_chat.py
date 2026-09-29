import json
from datetime import datetime, timedelta, timezone

import pytest
from gateway.src.providers.mock import MockProvider
from gateway.src.providers.registry import provider_registry
from httpx import AsyncClient


@pytest.fixture
async def setup_tenant_and_key(async_client: AsyncClient):
    """Helper fixture to create a valid tenant, project, and API key."""
    t_res = await async_client.post("/api/v1/tenants", json={"name": "Test Co", "slug": "test-co"})
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects", json={"name": "Core", "slug": "core"}
    )
    project_id = p_res.json()["id"]

    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "Dev Key"}
    )
    key_data = k_res.json()
    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "api_key_id": key_data["id"],
        "raw_key": key_data["key"],
        "headers": {"Authorization": f"Bearer {key_data['key']}"},
    }


# ============================================================
# 1. AUTHENTICATION TESTS
# ============================================================


@pytest.mark.asyncio
async def test_chat_missing_api_key(async_client: AsyncClient):
    payload = {"model": "mock-model", "messages": [{"role": "user", "content": "Hi"}]}
    res = await async_client.post("/v1/chat/completions", json=payload)
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid or expired API key"


@pytest.mark.asyncio
async def test_chat_invalid_api_key(async_client: AsyncClient):
    payload = {"model": "mock-model", "messages": [{"role": "user", "content": "Hi"}]}
    headers = {"Authorization": "Bearer tg_live_boguskey12345678"}
    res = await async_client.post("/v1/chat/completions", headers=headers, json=payload)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_chat_valid_api_key(async_client: AsyncClient, setup_tenant_and_key):
    payload = {"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]}
    res = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res.status_code == 200
    data = res.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "Hello from mock provider!"


@pytest.mark.asyncio
async def test_chat_revoked_api_key(async_client: AsyncClient, setup_tenant_and_key):
    # Revoke key
    key_id = setup_tenant_and_key["api_key_id"]
    del_res = await async_client.delete(f"/api/v1/api-keys/{key_id}")
    assert del_res.status_code == 200

    payload = {"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]}
    res = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_chat_expired_api_key(async_client: AsyncClient, setup_tenant_and_key):
    project_id = setup_tenant_and_key["project_id"]
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "Old Key", "expires_at": past}
    )
    expired_key = k_res.json()["key"]

    payload = {"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]}
    res = await async_client.post(
        "/v1/chat/completions", headers={"Authorization": f"Bearer {expired_key}"}, json=payload
    )
    assert res.status_code == 401


# ============================================================
# 2. REQUEST VALIDATION TESTS
# ============================================================


@pytest.mark.asyncio
async def test_validation_missing_model(async_client: AsyncClient, setup_tenant_and_key):
    payload = {"messages": [{"role": "user", "content": "Hi"}]}
    res = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res.status_code == 400
    err = res.json()
    assert "error" in err
    assert "model" in err["error"]["message"].lower()


@pytest.mark.asyncio
async def test_validation_missing_messages(async_client: AsyncClient, setup_tenant_and_key):
    payload = {"model": "mock-model"}
    res = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res.status_code == 400
    err = res.json()
    assert "error" in err


@pytest.mark.asyncio
async def test_validation_invalid_message_structure(
    async_client: AsyncClient, setup_tenant_and_key
):
    payload = {"model": "mock-model", "messages": [{"role": "nonexistent_role", "content": "Hi"}]}
    res = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res.status_code == 400
    assert "error" in res.json()


@pytest.mark.asyncio
async def test_validation_unsupported_parameter(async_client: AsyncClient, setup_tenant_and_key):
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hi"}],
        "unsupported_wild_param": 12345,
    }
    res = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res.status_code == 400
    assert "extra_forbidden" in str(res.json()) or "unsupported_wild_param" in str(res.json())


# ============================================================
# 3. PROVIDER EXECUTION & ERROR TESTS
# ============================================================


@pytest.mark.asyncio
async def test_unknown_model_returns_404(async_client: AsyncClient, setup_tenant_and_key):
    payload = {
        "model": "unknown-nonexistent-model-xyz",
        "messages": [{"role": "user", "content": "Hi"}],
    }
    res = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res.status_code == 404
    data = res.json()
    assert "error" in data
    assert "does not exist or is not configured" in data["error"]["message"]


@pytest.mark.asyncio
async def test_provider_failure(async_client: AsyncClient, setup_tenant_and_key):
    # Register a failing mock provider
    fail_provider = MockProvider(
        name="failing_mock",
        should_fail=True,
        failure_status=502,
        failure_message="Upstream crashed",
    )
    provider_registry.register_provider(fail_provider)
    provider_registry.register_route("fail-model", "failing_mock", "fail-model")

    payload = {"model": "fail-model", "messages": [{"role": "user", "content": "Hi"}]}
    res = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res.status_code == 502
    assert "Upstream crashed" in res.json()["error"]["message"]


@pytest.mark.asyncio
async def test_provider_timeout(async_client: AsyncClient, setup_tenant_and_key):
    timeout_provider = MockProvider(name="timeout_mock", should_timeout=True)
    provider_registry.register_provider(timeout_provider)
    provider_registry.register_route("timeout-model", "timeout_mock", "timeout-model")

    payload = {"model": "timeout-model", "messages": [{"role": "user", "content": "Hi"}]}
    res = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res.status_code == 504
    assert "timed out" in res.json()["error"]["message"]


# ============================================================
# 4. STREAMING TESTS (SSE)
# ============================================================


@pytest.mark.asyncio
async def test_streaming_sse_chunks(async_client: AsyncClient, setup_tenant_and_key):
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Count from 1 to 5"}],
        "stream": True,
    }
    res = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    lines = res.text.strip().split("\n\n")
    assert len(lines) > 2  # Multiple chunks + [DONE]

    chunks = []
    has_done = False
    for line in lines:
        if line.startswith("data: "):
            payload_str = line[6:]
            if payload_str == "[DONE]":
                has_done = True
            else:
                chunks.append(json.loads(payload_str))

    assert has_done is True
    assert len(chunks) >= 4
    first_chunk = chunks[0]
    assert first_chunk["object"] == "chat.completion.chunk"
    assert first_chunk["choices"][0]["delta"]["role"] == "assistant"


# ============================================================
# 5. REQUEST ID & HEADERS
# ============================================================


@pytest.mark.asyncio
async def test_request_id_echo_and_generation(async_client: AsyncClient, setup_tenant_and_key):
    # Case 1: Custom X-Request-ID
    custom_id = "req_custom_test_12345"
    headers = {**setup_tenant_and_key["headers"], "X-Request-ID": custom_id}
    payload = {"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]}

    res = await async_client.post("/v1/chat/completions", headers=headers, json=payload)
    assert res.status_code == 200
    assert res.headers["X-Request-ID"] == custom_id

    # Case 2: Generated X-Request-ID
    res_gen = await async_client.post(
        "/v1/chat/completions", headers=setup_tenant_and_key["headers"], json=payload
    )
    assert res_gen.status_code == 200
    assert "X-Request-ID" in res_gen.headers
    assert res_gen.headers["X-Request-ID"].startswith("req_")
