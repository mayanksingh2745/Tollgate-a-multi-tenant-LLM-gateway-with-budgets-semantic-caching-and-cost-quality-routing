import pytest
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.providers.base import (
    ProviderAuthenticationError,
    ProviderException,
    ProviderTimeoutError,
)
from gateway.src.providers.mock import MockProvider
from gateway.src.reliability.backoff import BackoffStrategy
from gateway.src.reliability.executor import ReliableExecutor
from gateway.src.reliability.policy import (
    FallbackRoute,
    ProviderTarget,
    ReliabilityPolicy,
)
from gateway.src.schemas.chat import ChatCompletionRequest, ChatMessage


def make_chat_request(model: str = "test-model") -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model=model,
        messages=[ChatMessage(role="user", content="Test message")],
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
async def test_retry_first_attempt_succeeds():
    provider = MockProvider(name="prov_a")
    route = FallbackRoute(
        logical_model="test-model",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
    )
    providers_map = {"prov_a": provider}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.01, jitter=False)
    )
    policy = ReliabilityPolicy(max_attempts=3, base_delay=0.001, max_delay=0.01)

    res, meta = await executor.execute_chat(
        request=make_chat_request(),
        route=route,
        providers_map=providers_map,
        ctx=make_ctx(),
        request_id="req_1",
        policy=policy,
    )

    assert res.choices[0].message.content == "Hello from mock provider!"
    assert provider.call_count == 1
    assert meta.total_attempts == 1
    assert meta.fallback_used is False


@pytest.mark.asyncio
async def test_retry_second_attempt_succeeds():
    # Fails once with 503, then succeeds on 2nd attempt
    provider = MockProvider(name="prov_a", failures_until_success=1, failure_status=503)
    route = FallbackRoute(
        logical_model="test-model",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
    )
    providers_map = {"prov_a": provider}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.01, jitter=False)
    )
    policy = ReliabilityPolicy(max_attempts=3, base_delay=0.001, max_delay=0.01)

    res, meta = await executor.execute_chat(
        request=make_chat_request(),
        route=route,
        providers_map=providers_map,
        ctx=make_ctx(),
        request_id="req_2",
        policy=policy,
    )

    assert res.choices[0].message.content == "Hello from mock provider!"
    assert provider.call_count == 2
    assert meta.total_attempts == 2
    assert meta.fallback_used is False


@pytest.mark.asyncio
async def test_retry_exhausted_raises_final_error():
    # Provider always fails with 500
    provider = MockProvider(
        name="prov_a", should_fail=True, failure_status=500, failure_message="Server exploded"
    )
    route = FallbackRoute(
        logical_model="test-model",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
    )
    providers_map = {"prov_a": provider}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.01, jitter=False)
    )
    policy = ReliabilityPolicy(max_attempts=3, base_delay=0.001, max_delay=0.01)

    with pytest.raises(ProviderException) as exc:
        await executor.execute_chat(
            request=make_chat_request(),
            route=route,
            providers_map=providers_map,
            ctx=make_ctx(),
            request_id="req_3",
            policy=policy,
        )

    assert "Server exploded" in str(exc.value)
    # Exactly max_attempts calls
    assert provider.call_count == 3


@pytest.mark.asyncio
async def test_non_retryable_400_no_retry():
    # 400 Bad Request should NOT be retried
    provider = MockProvider(
        name="prov_a", should_fail=True, failure_status=400, failure_message="Bad request"
    )
    route = FallbackRoute(
        logical_model="test-model",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
    )
    providers_map = {"prov_a": provider}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.01, jitter=False)
    )
    policy = ReliabilityPolicy(max_attempts=3, base_delay=0.001, max_delay=0.01)

    with pytest.raises(ProviderException) as exc:
        await executor.execute_chat(
            request=make_chat_request(),
            route=route,
            providers_map=providers_map,
            ctx=make_ctx(),
            request_id="req_4",
            policy=policy,
        )

    assert exc.value.status_code == 400
    # Must only call ONCE, zero retries
    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_auth_error_no_retry():
    # 401 Authentication failure should NOT be retried against same provider
    provider = MockProvider(
        name="prov_a", should_fail=True, failure_status=401, failure_message="Invalid API Key"
    )
    route = FallbackRoute(
        logical_model="test-model",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
    )
    providers_map = {"prov_a": provider}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.01, jitter=False)
    )
    policy = ReliabilityPolicy(max_attempts=3, base_delay=0.001, max_delay=0.01)

    with pytest.raises(ProviderAuthenticationError):
        await executor.execute_chat(
            request=make_chat_request(),
            route=route,
            providers_map=providers_map,
            ctx=make_ctx(),
            request_id="req_5",
            policy=policy,
        )

    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_rate_limit_429_retried_and_succeeds():
    # 429 fails once, then succeeds
    provider = MockProvider(
        name="prov_a",
        failures_until_success=1,
        failure_status=429,
        failure_message="Rate limit reached",
        retry_after=0.01,
    )
    route = FallbackRoute(
        logical_model="test-model",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
    )
    providers_map = {"prov_a": provider}

    executor = ReliableExecutor(
        backoff_strategy=BackoffStrategy(base_delay=0.001, max_delay=0.05, jitter=False)
    )
    policy = ReliabilityPolicy(max_attempts=3, base_delay=0.001, max_delay=0.05)

    res, meta = await executor.execute_chat(
        request=make_chat_request(),
        route=route,
        providers_map=providers_map,
        ctx=make_ctx(),
        request_id="req_6",
        policy=policy,
    )

    assert res.choices[0].message.content == "Hello from mock provider!"
    assert provider.call_count == 2
    assert meta.total_attempts == 2


@pytest.mark.asyncio
async def test_overall_deadline_stops_retries():
    # Provider sleeps 0.5s which exceeds the 0.1s overall deadline,
    # so asyncio.wait_for triggers TimeoutError on the first attempt.
    provider = MockProvider(
        name="prov_a", latency_seconds=0.5, should_fail=True, failure_status=504
    )
    route = FallbackRoute(
        logical_model="test-model",
        primary=ProviderTarget(provider_name="prov_a", upstream_model="model_a"),
    )
    providers_map = {"prov_a": provider}

    # Overall deadline of 0.1s is well below the 0.5s provider latency,
    # ensuring the first attempt is cancelled by asyncio.wait_for.
    policy = ReliabilityPolicy(
        max_attempts=5, base_delay=0.01, max_delay=0.02, overall_timeout_seconds=0.1
    )
    executor = ReliableExecutor()

    with pytest.raises((ProviderTimeoutError, ProviderException)):
        await executor.execute_chat(
            request=make_chat_request(),
            route=route,
            providers_map=providers_map,
            ctx=make_ctx(),
            request_id="req_7",
            policy=policy,
        )

    # Must be bounded by deadline rather than running all 5 attempts
    assert provider.call_count < 5
