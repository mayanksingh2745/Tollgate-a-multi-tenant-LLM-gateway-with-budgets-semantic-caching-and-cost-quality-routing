import uuid
from datetime import datetime, timedelta, timezone

import pytest
from gateway.src.cache.semantic.backend import InMemorySemanticCacheBackend
from gateway.src.cache.semantic.embeddings import MockEmbeddingProvider
from gateway.src.cache.semantic.representation import (
    SemanticRepresentation,
)
from gateway.src.schemas.chat import (
    ChatCompletionRequest,
    ChatMessage,
)


@pytest.mark.asyncio
async def test_semantic_representation_formatting():
    req = ChatCompletionRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(
                role="system", content="You are a helpful assistant.\nKeep answers concise."
            ),
            ChatMessage(role="user", content="  What is TCP?  "),
            ChatMessage(role="assistant", content="TCP is Transmission Control Protocol."),
            ChatMessage(role="user", content="How does it work?"),
        ],
    )
    text = SemanticRepresentation.build_text_to_embed(req)
    assert "role=system\ncontent=You are a helpful assistant.\nKeep answers concise." in text
    assert "role=user\ncontent=  What is TCP?  " in text
    assert "role=assistant\ncontent=TCP is Transmission Control Protocol." in text
    assert "role=user\ncontent=How does it work?" in text
    # Verify order is preserved
    assert text.index("role=system") < text.index("What is TCP?") < text.index("How does it work?")


def test_compatibility_fingerprint_normalization():
    t_id = uuid.uuid4()
    p_id = uuid.uuid4()

    req1 = ChatCompletionRequest(
        model="GPT-4o",
        messages=[ChatMessage(role="user", content="Hello")],
        temperature=1.0,
        top_p=1.0,
    )
    req2 = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="Different message")],
        temperature=None,  # Defaults to 1.0
        top_p=None,  # Defaults to 1.0
    )

    fp1 = SemanticRepresentation.compute_fingerprint(req1, t_id, p_id, "OpenAI")
    fp2 = SemanticRepresentation.compute_fingerprint(req2, t_id, p_id, "openai")
    # Same generation config and scope produces exact same fingerprint despite message difference
    assert fp1 == fp2

    # Different temperature produces distinct fingerprint
    req3 = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="Hello")],
        temperature=0.7,
    )
    fp3 = SemanticRepresentation.compute_fingerprint(req3, t_id, p_id, "openai")
    assert fp1 != fp3


@pytest.mark.asyncio
async def test_mock_embedding_provider_determinism():
    provider = MockEmbeddingProvider()

    v1 = await provider.embed("How does TCP congestion control work?")
    v2 = await provider.embed("How does TCP congestion control work?")
    assert v1 == v2
    assert len(v1) == 1536

    # Unit norm check
    norm_sq = sum(x * x for x in v1)
    assert pytest.approx(norm_sq, 0.001) == 1.0


@pytest.mark.asyncio
async def test_dangerous_near_matches_similarity():
    provider = MockEmbeddingProvider()

    v_delete = await provider.embed("How do I delete a database?")
    v_create = await provider.embed("How do I create a database?")
    sim_db = sum(a * b for a, b in zip(v_delete, v_create, strict=True))

    v_pass = await provider.embed("How do I reset my password?")
    v_router = await provider.embed("How do I reset my router?")
    sim_reset = sum(a * b for a, b in zip(v_pass, v_router, strict=True))

    # Crucial safety invariant: dangerous near-matches must not exceed conservative threshold (0.85)
    assert sim_db < 0.75
    assert sim_reset < 0.75


def test_cacheability_bypass_rules():
    # Streaming bypass
    req_stream = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )
    cacheable, reason = SemanticRepresentation.is_cacheable(req_stream)
    assert not cacheable
    assert reason == "streaming_not_supported"

    # Tool definitions bypass
    req_tools = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="Hi")],
        tools=[{"type": "function", "function": {"name": "test"}}],
    )
    cacheable, reason = SemanticRepresentation.is_cacheable(req_tools)
    assert not cacheable
    assert reason == "tools_present"

    # Tool choice bypass
    req_tool_choice = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="Hi")],
        tool_choice="required",
    )
    cacheable, reason = SemanticRepresentation.is_cacheable(req_tool_choice)
    assert not cacheable
    assert reason == "tool_choice_present"

    # Multiple choices bypass
    req_n = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="Hi")],
        n=2,
    )
    cacheable, reason = SemanticRepresentation.is_cacheable(req_n)
    assert not cacheable
    assert reason == "multiple_completions_not_supported"


@pytest.mark.asyncio
async def test_backend_top_k_and_expiration():
    backend = InMemorySemanticCacheBackend()
    t_id = uuid.uuid4()
    p_id = uuid.uuid4()

    # Store 3 entries
    now = datetime.now(timezone.utc)
    for i in range(3):
        await backend.store_entry(
            tenant_id=t_id,
            project_id=p_id,
            provider="openai",
            model="gpt-4o",
            fingerprint="fp1",
            semantic_representation=f"repr {i}",
            embedding=[0.1 * i] * 1536,
            embedding_model="mock-v1",
            embedding_version="v1",
            response_cache_key=f"key_{i}",
            expires_at=now + timedelta(seconds=100),
        )

    # Store 1 expired entry
    await backend.store_entry(
        tenant_id=t_id,
        project_id=p_id,
        provider="openai",
        model="gpt-4o",
        fingerprint="fp1",
        semantic_representation="expired",
        embedding=[0.5] * 1536,
        embedding_model="mock-v1",
        embedding_version="v1",
        response_cache_key="key_expired",
        expires_at=now - timedelta(seconds=10),
    )

    # Top-K = 2
    candidates = await backend.search_candidates(
        tenant_id=t_id,
        project_id=p_id,
        provider="openai",
        model="gpt-4o",
        fingerprint="fp1",
        query_embedding=[0.0] * 1536,
        top_k=2,
    )
    assert len(candidates) == 2
    # Expired entry must not be returned
    assert all(c.response_cache_key != "key_expired" for c in candidates)
