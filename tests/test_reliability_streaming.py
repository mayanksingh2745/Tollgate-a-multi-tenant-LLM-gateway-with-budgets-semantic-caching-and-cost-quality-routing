import json

import pytest
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.providers.mock import MockProvider
from gateway.src.reliability.backoff import BackoffStrategy
from gateway.src.reliability.executor import ReliableExecutor
from gateway.src.reliability.policy import (
    FallbackRoute,
    ProviderTarget,
    ReliabilityPolicy,
)
from gateway.src.schemas.chat import ChatCompletionRequest, ChatMessage


def make_stream_request(model: str = "stream-test") -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model=model,
        messages=[ChatMessage(role="user", content="Stream text")],
        stream=True,
    )


def make_ctx() -> AuthenticatedContext:
    from uuid import uuid4

    return AuthenticatedContext(tenant_id=uuid4(), project_id=uuid4(), api_key_id=uuid4())


@pytest.mark.asyncio
async def test_streaming_success():
    prov_a = MockProvider(name="prov_a", response_text="One Two Three Four")
    route = FallbackRoute(
        logical_model="stream-test",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
    )
    providers_map = {"prov_a": prov_a}

    executor = ReliableExecutor()
    chunks = []
    has_done = False

    async for item in executor.execute_stream(
        request=make_stream_request(),
        route=route,
        providers_map=providers_map,
        ctx=make_ctx(),
        request_id="req_str_1",
    ):
        if item.strip() == "data: [DONE]":
            has_done = True
        elif item.startswith("data: "):
            chunks.append(json.loads(item[6:]))

    assert has_done is True
    assert len(chunks) >= 4
    assert prov_a.call_count == 1


@pytest.mark.asyncio
async def test_streaming_failure_before_first_chunk_retries_and_falls_back():
    # Primary fails BEFORE emitting any chunk
    prov_a = MockProvider(name="prov_a", failure_mode="stream_before")
    prov_b = MockProvider(name="prov_b", response_text="Fallback Stream Success")

    route = FallbackRoute(
        logical_model="stream-test",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
        fallbacks=[ProviderTarget(provider_name="prov_b", upstream_model="model_b")],
    )
    providers_map = {"prov_a": prov_a, "prov_b": prov_b}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.01, jitter=False)
    )
    policy = ReliabilityPolicy(max_attempts=1, base_delay=0.001, max_delay=0.01)

    received_text = []
    has_done = False

    async for item in executor.execute_stream(
        request=make_stream_request(),
        route=route,
        providers_map=providers_map,
        ctx=make_ctx(),
        request_id="req_str_2",
        policy=policy,
    ):
        if item.strip() == "data: [DONE]":
            has_done = True
        elif item.startswith("data: "):
            chunk = json.loads(item[6:])
            if "choices" in chunk and chunk["choices"][0]["delta"].get("content"):
                received_text.append(chunk["choices"][0]["delta"]["content"])

    assert has_done is True
    assert "".join(received_text) == "Fallback Stream Success"
    assert prov_a.call_count == 1
    assert prov_b.call_count == 1


@pytest.mark.asyncio
async def test_streaming_failure_after_chunks_no_restart():
    # Primary emits 2 chunks and then disconnects mid-stream
    # CRITICAL RULE: DO NOT transparently restart or call Fallback B!
    prov_a = MockProvider(
        name="prov_a", failure_mode="stream_after", response_text="Word1 Word2 Word3 Word4 Word5"
    )
    prov_b = MockProvider(name="prov_b", response_text="UNWANTED DUPLICATE")

    route = FallbackRoute(
        logical_model="stream-test",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
        fallbacks=[ProviderTarget(provider_name="prov_b", upstream_model="model_b")],
    )
    providers_map = {"prov_a": prov_a, "prov_b": prov_b}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.01, jitter=False)
    )

    items = []
    async for item in executor.execute_stream(
        request=make_stream_request(),
        route=route,
        providers_map=providers_map,
        ctx=make_ctx(),
        request_id="req_str_3",
    ):
        items.append(item)

    # Must contain error payload and terminated [DONE]
    full_stream = "".join(items)
    assert "stream_interrupted" in full_stream or "error" in full_stream
    assert "data: [DONE]" in full_stream

    # Fallback B must NEVER be called after partial delivery!
    assert prov_b.call_count == 0
    assert "UNWANTED DUPLICATE" not in full_stream
