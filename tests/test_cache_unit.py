import uuid

import pytest
from gateway.src.cache.canonicalizer import Canonicalizer
from gateway.src.cache.service import (
    ExactResponseCache,
    InMemoryCacheBackend,
)
from gateway.src.config import settings
from gateway.src.schemas.chat import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ResponseFormat,
    UsageInfo,
)


@pytest.mark.asyncio
async def test_canonicalizer_message_order():
    """Verify that message order is strictly preserved and affects the cache hash."""
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()

    req_1 = ChatCompletionRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there"),
        ],
    )
    req_2 = ChatCompletionRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="assistant", content="Hi there"),
            ChatMessage(role="user", content="Hello"),
        ],
    )

    hash_1 = Canonicalizer.compute_hash(req_1, tenant_id, project_id, "openai")
    hash_2 = Canonicalizer.compute_hash(req_2, tenant_id, project_id, "openai")

    assert hash_1 != hash_2, "Different message order must produce different cache hashes"


@pytest.mark.asyncio
async def test_canonicalizer_whitespace_preservation():
    """Verify that prompt whitespace differences produce different cache hashes."""
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()

    req_1 = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="hello world")],
    )
    req_2 = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="hello world ")],
    )

    hash_1 = Canonicalizer.compute_hash(req_1, tenant_id, project_id, "openai")
    hash_2 = Canonicalizer.compute_hash(req_2, tenant_id, project_id, "openai")

    assert hash_1 != hash_2, "Trailing whitespace must not be silently stripped"


@pytest.mark.asyncio
async def test_canonicalizer_omitted_vs_explicit_defaults():
    """Verify that omitted parameters (None) vs explicit values (e.g. temperature=0.0) produce different hashes."""
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()

    req_omitted = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="Calculate sum")],
        temperature=None,
    )
    req_explicit_zero = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="Calculate sum")],
        temperature=0.0,
    )

    hash_omitted = Canonicalizer.compute_hash(req_omitted, tenant_id, project_id, "openai")
    hash_explicit = Canonicalizer.compute_hash(req_explicit_zero, tenant_id, project_id, "openai")

    assert (
        hash_omitted != hash_explicit
    ), "Omitted temperature must produce a different key than explicit 0.0"


@pytest.mark.asyncio
async def test_canonicalizer_generation_parameters():
    """Verify that all generation-affecting parameters influence the cache key."""
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()

    base_req = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="Generate test")],
    )
    base_hash = Canonicalizer.compute_hash(base_req, tenant_id, project_id, "openai")

    # top_p
    req_top_p = base_req.model_copy(update={"top_p": 0.8})
    assert Canonicalizer.compute_hash(req_top_p, tenant_id, project_id, "openai") != base_hash

    # max_tokens
    req_max_tokens = base_req.model_copy(update={"max_tokens": 500})
    assert Canonicalizer.compute_hash(req_max_tokens, tenant_id, project_id, "openai") != base_hash

    # stop (single string vs list)
    req_stop_str = base_req.model_copy(update={"stop": "END"})
    req_stop_list = base_req.model_copy(update={"stop": ["END"]})
    assert Canonicalizer.compute_hash(
        req_stop_str, tenant_id, project_id, "openai"
    ) == Canonicalizer.compute_hash(req_stop_list, tenant_id, project_id, "openai")

    # seed
    req_seed = base_req.model_copy(update={"seed": 42})
    assert Canonicalizer.compute_hash(req_seed, tenant_id, project_id, "openai") != base_hash

    # response_format
    req_json = base_req.model_copy(update={"response_format": ResponseFormat(type="json_object")})
    assert Canonicalizer.compute_hash(req_json, tenant_id, project_id, "openai") != base_hash

    # penalties
    req_pres = base_req.model_copy(update={"presence_penalty": 0.5})
    assert Canonicalizer.compute_hash(req_pres, tenant_id, project_id, "openai") != base_hash


@pytest.mark.asyncio
async def test_cacheability_policy():
    """Verify safe bypass conditions: streaming, tools, tool_choice, disabled cache."""
    # Standard request is cacheable
    normal_req = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="test")],
    )
    cacheable, reason = Canonicalizer.is_cacheable(normal_req)
    assert cacheable is True
    assert reason is None

    # Streaming bypass
    stream_req = normal_req.model_copy(update={"stream": True})
    cacheable, reason = Canonicalizer.is_cacheable(stream_req)
    assert cacheable is False
    assert reason == "streaming_bypass"

    # Tools bypass
    tools_req = normal_req.model_copy(
        update={"tools": [{"type": "function", "function": {"name": "get_weather"}}]}
    )
    cacheable, reason = Canonicalizer.is_cacheable(tools_req)
    assert cacheable is False
    assert reason == "tools_bypass"

    # Tool choice bypass
    tool_choice_req = normal_req.model_copy(update={"tool_choice": "auto"})
    cacheable, reason = Canonicalizer.is_cacheable(tool_choice_req)
    assert cacheable is False
    assert reason == "tools_bypass"


@pytest.mark.asyncio
async def test_response_size_limit():
    """Verify that responses exceeding cache_max_response_bytes are rejected from cache write."""
    backend = InMemoryCacheBackend()
    cache = ExactResponseCache(backend=backend)
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()

    req = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="give huge output")],
    )

    # Construct response larger than configured max size
    huge_content = "X" * (settings.cache_max_response_bytes + 1000)
    huge_resp = ChatCompletionResponse(
        id="chatcmpl-huge",
        created=123456789,
        model="gpt-4o",
        choices=[
            ChatChoice(
                index=0,
                message=ChatChoiceMessage(role="assistant", content=huge_content),
                finish_reason="stop",
            )
        ],
        usage=UsageInfo(prompt_tokens=10, completion_tokens=100000, total_tokens=100010),
    )

    written = await cache.set(req, huge_resp, tenant_id, project_id, "openai")
    assert written is False, "Response exceeding max bytes must not be stored in cache"

    lookup = await cache.get(req, tenant_id, project_id, "openai")
    assert lookup is None, "Should be a cache MISS after size overage rejection"


@pytest.mark.asyncio
async def test_schema_version_mismatch_invalidation():
    """Verify that cache entries with outdated schema version are treated as misses and deleted."""
    backend = InMemoryCacheBackend()
    cache = ExactResponseCache(backend=backend)
    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()

    req = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="version test")],
    )

    # Manually store outdated schema entry (cache_version = 999)
    cache_key = await cache._build_cache_key(req, tenant_id, project_id, "openai")
    outdated_payload = {
        "cache_version": 999,
        "tenant_id": str(tenant_id),
        "project_id": str(project_id),
        "response": {"id": "old", "choices": [], "model": "gpt-4o", "created": 100},
    }
    import json

    await backend.set(cache_key, json.dumps(outdated_payload), 300)

    # Lookup should detect mismatched version, invalidate entry, and return None
    result = await cache.get(req, tenant_id, project_id, "openai")
    assert result is None

    # Entry should have been removed from backend
    raw = await backend.get(cache_key)
    assert raw is None
