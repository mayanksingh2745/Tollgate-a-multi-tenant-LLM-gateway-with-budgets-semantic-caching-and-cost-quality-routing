import pytest
from gateway.src.main import app
from httpx import ASGITransport, AsyncClient
from openai import AsyncOpenAI


@pytest.mark.asyncio
async def test_openai_sdk_non_streaming_compatibility(async_client: AsyncClient):
    # 1. Setup tenant & API key via async_client
    t_res = await async_client.post(
        "/api/v1/tenants", json={"name": "SDK Tenant", "slug": "sdk-tenant"}
    )
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects", json={"name": "SDK Project", "slug": "sdk-proj"}
    )
    project_id = p_res.json()["id"]

    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "SDK Key"}
    )
    raw_key = k_res.json()["key"]

    # 2. Instantiate OpenAI SDK AsyncOpenAI client routed to Tollgate
    transport = ASGITransport(app=app)
    custom_http_client = AsyncClient(transport=transport, base_url="http://testserver")

    client = AsyncOpenAI(
        api_key=raw_key,
        base_url="http://testserver/v1",
        http_client=custom_http_client,
    )

    # 3. Call chat.completions.create (non-streaming)
    response = await client.chat.completions.create(
        model="mock-model",
        messages=[{"role": "user", "content": "Hello via OpenAI Python SDK!"}],
        stream=False,
    )

    # 4. Verify OpenAI SDK parsed response objects properly
    assert response.id.startswith("chatcmpl-")
    assert response.object == "chat.completion"
    assert len(response.choices) == 1
    assert response.choices[0].message.role == "assistant"
    assert response.choices[0].message.content == "Hello from mock provider!"
    assert response.usage is not None
    assert response.usage.total_tokens > 0


@pytest.mark.asyncio
async def test_openai_sdk_streaming_compatibility(async_client: AsyncClient):
    # 1. Setup tenant & API key
    t_res = await async_client.post(
        "/api/v1/tenants", json={"name": "Stream Tenant", "slug": "stream-tenant"}
    )
    tenant_id = t_res.json()["id"]

    p_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "Stream Project", "slug": "stream-proj"},
    )
    project_id = p_res.json()["id"]

    k_res = await async_client.post(
        f"/api/v1/projects/{project_id}/api-keys", json={"name": "Stream Key"}
    )
    raw_key = k_res.json()["key"]

    # 2. Instantiate OpenAI SDK client
    transport = ASGITransport(app=app)
    custom_http_client = AsyncClient(transport=transport, base_url="http://testserver")

    client = AsyncOpenAI(
        api_key=raw_key,
        base_url="http://testserver/v1",
        http_client=custom_http_client,
    )

    # 3. Call chat.completions.create (streaming)
    stream = await client.chat.completions.create(
        model="mock-model",
        messages=[{"role": "user", "content": "Stream to me!"}],
        stream=True,
    )

    chunks = []
    collected_content = []
    async for chunk in stream:
        chunks.append(chunk)
        if chunk.choices and chunk.choices[0].delta.content:
            collected_content.append(chunk.choices[0].delta.content)

    assert len(chunks) >= 4
    full_text = "".join(collected_content)
    assert full_text == "Hello from mock provider!"
