import pytest
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.providers.base import ProviderException
from gateway.src.providers.mock import MockProvider
from gateway.src.reliability.backoff import BackoffStrategy
from gateway.src.reliability.executor import ReliableExecutor
from gateway.src.reliability.policy import (
    FallbackRoute,
    ProviderTarget,
    ReliabilityPolicy,
)
from gateway.src.schemas.chat import ChatCompletionRequest, ChatMessage


def make_chat_request(model: str = "fallback-test") -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model=model,
        messages=[ChatMessage(role="user", content="Hello fallback")],
        stream=False,
    )


def make_ctx() -> AuthenticatedContext:
    from uuid import uuid4

    return AuthenticatedContext(
        tenant_id=uuid4(),
        project_id=uuid4(),
        api_key_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_fallback_primary_succeeds():
    prov_a = MockProvider(name="prov_a", response_text="Response from Primary")
    prov_b = MockProvider(name="prov_b", response_text="Response from Fallback")

    route = FallbackRoute(
        logical_model="fallback-test",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
        fallbacks=[ProviderTarget(provider_name="prov_b", upstream_model="model_b")],
    )
    providers_map = {"prov_a": prov_a, "prov_b": prov_b}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.01, jitter=False)
    )
    policy = ReliabilityPolicy(max_attempts=2, base_delay=0.001, max_delay=0.01)

    res, meta = await executor.execute_chat(
        request=make_chat_request(),
        route=route,
        providers_map=providers_map,
        ctx=make_ctx(),
        request_id="req_fb_1",
        policy=policy,
    )

    assert res.choices[0].message.content == "Response from Primary"
    assert prov_a.call_count == 1
    assert prov_b.call_count == 0
    assert meta.fallback_used is False


@pytest.mark.asyncio
async def test_fallback_on_primary_failure():
    # Primary always 503
    prov_a = MockProvider(
        name="prov_a", should_fail=True, failure_status=503, failure_message="Primary unavailable"
    )
    prov_b = MockProvider(name="prov_b", response_text="Response from Fallback B")

    route = FallbackRoute(
        logical_model="fallback-test",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
        fallbacks=[ProviderTarget(provider_name="prov_b", upstream_model="model_b")],
    )
    providers_map = {"prov_a": prov_a, "prov_b": prov_b}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.01, jitter=False)
    )
    policy = ReliabilityPolicy(max_attempts=2, base_delay=0.001, max_delay=0.01)

    res, meta = await executor.execute_chat(
        request=make_chat_request(),
        route=route,
        providers_map=providers_map,
        ctx=make_ctx(),
        request_id="req_fb_2",
        policy=policy,
    )

    assert res.choices[0].message.content == "Response from Fallback B"
    assert prov_a.call_count == 2  # Attempted max_attempts on primary
    assert prov_b.call_count == 1  # Succeeded on fallback
    assert meta.fallback_used is True
    assert meta.final_provider == "prov_b"


@pytest.mark.asyncio
async def test_fallback_not_used_on_client_400():
    # Primary 400 Bad Request should NOT trigger fallback
    prov_a = MockProvider(
        name="prov_a", should_fail=True, failure_status=400, failure_message="Client error"
    )
    prov_b = MockProvider(name="prov_b", response_text="Should not be called")

    route = FallbackRoute(
        logical_model="fallback-test",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
        fallbacks=[ProviderTarget(provider_name="prov_b", upstream_model="model_b")],
    )
    providers_map = {"prov_a": prov_a, "prov_b": prov_b}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.01, jitter=False)
    )
    policy = ReliabilityPolicy(max_attempts=2, base_delay=0.001, max_delay=0.01)

    with pytest.raises(ProviderException) as exc:
        await executor.execute_chat(
            request=make_chat_request(),
            route=route,
            providers_map=providers_map,
            ctx=make_ctx(),
            request_id="req_fb_3",
            policy=policy,
        )

    assert exc.value.status_code == 400
    assert prov_a.call_count == 1
    assert prov_b.call_count == 0  # Fallback was not called


@pytest.mark.asyncio
async def test_multiple_fallbacks_in_order():
    # Primary fails (503), Fallback 1 fails (502), Fallback 2 succeeds
    prov_a = MockProvider(name="prov_a", should_fail=True, failure_status=503)
    prov_b = MockProvider(name="prov_b", should_fail=True, failure_status=502)
    prov_c = MockProvider(name="prov_c", response_text="Response from Fallback C")

    route = FallbackRoute(
        logical_model="multi-fallback",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
        fallbacks=[
            ProviderTarget(provider_name="prov_b", upstream_model="model_b"),
            ProviderTarget(provider_name="prov_c", upstream_model="model_c"),
        ],
    )
    providers_map = {"prov_a": prov_a, "prov_b": prov_b, "prov_c": prov_c}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.01, jitter=False)
    )
    policy = ReliabilityPolicy(max_attempts=1, base_delay=0.001, max_delay=0.01)

    res, meta = await executor.execute_chat(
        request=make_chat_request(model="multi-fallback"),
        route=route,
        providers_map=providers_map,
        ctx=make_ctx(),
        request_id="req_fb_4",
        policy=policy,
    )

    assert res.choices[0].message.content == "Response from Fallback C"
    assert prov_a.call_count == 1
    assert prov_b.call_count == 1
    assert prov_c.call_count == 1
    assert meta.final_provider == "prov_c"
    assert meta.fallback_used is True
    assert meta.providers_attempted == ["prov_a", "prov_b", "prov_c"]


@pytest.mark.asyncio
async def test_all_fallbacks_fail_normalized_error():
    prov_a = MockProvider(
        name="prov_a", should_fail=True, failure_status=503, failure_message="A failed"
    )
    prov_b = MockProvider(
        name="prov_b", should_fail=True, failure_status=503, failure_message="B failed"
    )

    route = FallbackRoute(
        logical_model="all-fail",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
        fallbacks=[ProviderTarget(provider_name="prov_b", upstream_model="model_b")],
    )
    providers_map = {"prov_a": prov_a, "prov_b": prov_b}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.01, jitter=False)
    )
    policy = ReliabilityPolicy(max_attempts=1, base_delay=0.001, max_delay=0.01)

    with pytest.raises(ProviderException) as exc:
        await executor.execute_chat(
            request=make_chat_request(model="all-fail"),
            route=route,
            providers_map=providers_map,
            ctx=make_ctx(),
            request_id="req_fb_5",
            policy=policy,
        )

    assert exc.value.status_code == 503
    assert prov_a.call_count == 1
    assert prov_b.call_count == 1
