import pytest
from httpx import AsyncClient


@pytest.fixture
async def setup_two_tenants_and_projects(async_client: AsyncClient):
    # Tenant A with two projects
    t_a = (
        await async_client.post("/api/v1/tenants", json={"name": "Tenant A", "slug": "tenant-a"})
    ).json()
    p_a1 = (
        await async_client.post(
            f"/api/v1/tenants/{t_a['id']}/projects", json={"name": "Proj A1", "slug": "proj-a1"}
        )
    ).json()
    p_a2 = (
        await async_client.post(
            f"/api/v1/tenants/{t_a['id']}/projects", json={"name": "Proj A2", "slug": "proj-a2"}
        )
    ).json()
    k_a1_1 = (
        await async_client.post(
            f"/api/v1/projects/{p_a1['id']}/api-keys", json={"name": "Key A1-1"}
        )
    ).json()
    k_a1_2 = (
        await async_client.post(
            f"/api/v1/projects/{p_a1['id']}/api-keys", json={"name": "Key A1-2"}
        )
    ).json()
    k_a2 = (
        await async_client.post(f"/api/v1/projects/{p_a2['id']}/api-keys", json={"name": "Key A2"})
    ).json()

    # Tenant B with one project
    t_b = (
        await async_client.post("/api/v1/tenants", json={"name": "Tenant B", "slug": "tenant-b"})
    ).json()
    p_b = (
        await async_client.post(
            f"/api/v1/tenants/{t_b['id']}/projects", json={"name": "Proj B", "slug": "proj-b"}
        )
    ).json()
    k_b = (
        await async_client.post(f"/api/v1/projects/{p_b['id']}/api-keys", json={"name": "Key B"})
    ).json()

    return {
        "t_a": t_a,
        "p_a1": p_a1,
        "p_a2": p_a2,
        "headers_a1_1": {"Authorization": f"Bearer {k_a1_1['key']}"},
        "headers_a1_2": {"Authorization": f"Bearer {k_a1_2['key']}"},
        "headers_a2": {"Authorization": f"Bearer {k_a2['key']}"},
        "t_b": t_b,
        "p_b": p_b,
        "headers_b": {"Authorization": f"Bearer {k_b['key']}"},
    }


@pytest.mark.asyncio
async def test_cross_tenant_cache_isolation(
    async_client: AsyncClient, setup_two_tenants_and_projects
):
    """
    Mandatory Scenario:
    Tenant A sends prompt "What is the capital of France?" -> MISS -> calls provider -> caches response.
    Tenant B sends identical prompt "What is the capital of France?" -> MISS -> calls provider.
    Tenant B must NEVER hit Tenant A's cached response.
    Tenant A's second identical request -> HIT -> returns cached response.
    """
    data = setup_two_tenants_and_projects
    req_payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "What is the capital of France?"}],
        "temperature": 0.0,
    }

    # 1. Tenant A first request -> MISS
    resp_a1 = await async_client.post(
        "/v1/chat/completions",
        headers=data["headers_a1_1"],
        json=req_payload,
    )
    assert resp_a1.status_code == 200
    assert resp_a1.headers.get("X-Tollgate-Cache") == "MISS"
    content_a1 = resp_a1.json()["choices"][0]["message"]["content"]

    # 2. Tenant B identical request -> MISS (cross-tenant isolation prevents hitting Tenant A cache)
    resp_b = await async_client.post(
        "/v1/chat/completions",
        headers=data["headers_b"],
        json=req_payload,
    )
    assert resp_b.status_code == 200
    assert resp_b.headers.get("X-Tollgate-Cache") == "MISS"

    # 3. Tenant A second identical request -> HIT
    resp_a2 = await async_client.post(
        "/v1/chat/completions",
        headers=data["headers_a1_1"],
        json=req_payload,
    )
    assert resp_a2.status_code == 200
    assert resp_a2.headers.get("X-Tollgate-Cache") == "HIT"
    assert resp_a2.json()["choices"][0]["message"]["content"] == content_a1


@pytest.mark.asyncio
async def test_cross_project_cache_isolation(
    async_client: AsyncClient, setup_two_tenants_and_projects
):
    """
    Verify that Project 1 and Project 2 in the same Tenant have isolated caches.
    """
    data = setup_two_tenants_and_projects
    req_payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Write a python function to compute factorial."}],
        "temperature": 0.5,
    }

    # Project A1 request -> MISS
    resp_a1 = await async_client.post(
        "/v1/chat/completions",
        headers=data["headers_a1_1"],
        json=req_payload,
    )
    assert resp_a1.status_code == 200
    assert resp_a1.headers.get("X-Tollgate-Cache") == "MISS"

    # Project A2 request with same prompt -> MISS (isolated project boundary)
    resp_a2 = await async_client.post(
        "/v1/chat/completions",
        headers=data["headers_a2"],
        json=req_payload,
    )
    assert resp_a2.status_code == 200
    assert resp_a2.headers.get("X-Tollgate-Cache") == "MISS"


@pytest.mark.asyncio
async def test_api_key_sharing_within_same_project(
    async_client: AsyncClient, setup_two_tenants_and_projects
):
    """
    Verify that different API keys within the same project share the exact cache entries.
    """
    data = setup_two_tenants_and_projects
    req_payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Explain quantum computing in one sentence."}],
    }

    # Key 1 in Project A1 -> MISS
    resp_key1 = await async_client.post(
        "/v1/chat/completions",
        headers=data["headers_a1_1"],
        json=req_payload,
    )
    assert resp_key1.status_code == 200
    assert resp_key1.headers.get("X-Tollgate-Cache") == "MISS"

    # Key 2 in same Project A1 -> HIT (shared cache within project boundary)
    resp_key2 = await async_client.post(
        "/v1/chat/completions",
        headers=data["headers_a1_2"],
        json=req_payload,
    )
    assert resp_key2.status_code == 200
    assert resp_key2.headers.get("X-Tollgate-Cache") == "HIT"
    assert (
        resp_key2.json()["choices"][0]["message"]["content"]
        == resp_key1.json()["choices"][0]["message"]["content"]
    )


@pytest.mark.asyncio
async def test_model_isolation(async_client: AsyncClient, setup_two_tenants_and_projects):
    """
    Verify that same prompt sent to different models produces independent cache keys.
    """
    data = setup_two_tenants_and_projects
    prompt = [{"role": "user", "content": "Tell me a joke."}]

    # Request to mock-model -> MISS
    resp_gpt4o = await async_client.post(
        "/v1/chat/completions",
        headers=data["headers_a1_1"],
        json={"model": "mock-model", "messages": prompt},
    )
    assert resp_gpt4o.status_code == 200
    assert resp_gpt4o.headers.get("X-Tollgate-Cache") == "MISS"

    # Request with identical prompt to mock-fast -> MISS (different model identity)
    resp_mini = await async_client.post(
        "/v1/chat/completions",
        headers=data["headers_a1_1"],
        json={"model": "mock-fast", "messages": prompt},
    )
    assert resp_mini.status_code == 200
    assert resp_mini.headers.get("X-Tollgate-Cache") == "MISS"
