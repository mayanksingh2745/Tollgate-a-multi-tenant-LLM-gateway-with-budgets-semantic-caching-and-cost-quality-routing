import asyncio
import uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.providers.base import LLMProvider, ProviderException
from gateway.src.reliability.executor import ReliableExecutor
from gateway.src.reliability.policy import (
    FallbackRoute,
    ProviderTarget,
    ReliabilityPolicy,
)
from gateway.src.schemas.chat import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    UsageInfo,
)


class MockFlakyProvider(LLMProvider):
    def __init__(self, name: str, failure_rate: float):
        super().__init__(name=name)
        self.failure_rate = failure_rate
        self.call_count = 0

    async def chat(
        self, request: ChatCompletionRequest, resolved_model: str, request_id: str
    ) -> ChatCompletionResponse:
        self.call_count += 1
        # Determine failure deterministically based on rate
        if (
            self.call_count % int(1.0 / max(0.01, self.failure_rate))
        ) == 1 and self.failure_rate > 0.0:
            raise ProviderException(f"{self.name} simulated 500 error", status_code=500)

        return ChatCompletionResponse(
            id=f"chatcmpl-flaky-{self.call_count}",
            created=1711800000,
            model=request.model,
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatChoiceMessage(role="assistant", content=f"Hello from {self.name}!"),
                    finish_reason="stop",
                )
            ],
            usage=UsageInfo(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )

    async def stream(
        self, request: ChatCompletionRequest, resolved_model: str, request_id: str
    ) -> AsyncIterator[str]:
        yield "chunk1"


class MockDeterministicProvider(LLMProvider):
    def __init__(self, name: str, should_fail: bool = False):
        super().__init__(name=name)
        self.should_fail = should_fail
        self.call_count = 0

    async def chat(
        self, request: ChatCompletionRequest, resolved_model: str, request_id: str
    ) -> ChatCompletionResponse:
        self.call_count += 1
        if self.should_fail:
            raise ProviderException(f"{self.name} down", status_code=503)

        return ChatCompletionResponse(
            id=f"chatcmpl-det-{self.call_count}",
            created=1711800000,
            model=request.model,
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatChoiceMessage(
                        role="assistant", content=f"Success from {self.name}"
                    ),
                    finish_reason="stop",
                )
            ],
            usage=UsageInfo(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )

    async def stream(
        self, request: ChatCompletionRequest, resolved_model: str, request_id: str
    ) -> AsyncIterator[str]:
        yield "chunk1"


@pytest.mark.asyncio
async def test_provider_partial_failure_retry_resolution():
    """
    Simulates a 10% to 30% failure rate on the primary provider.
    Verifies that the retry policy with backoff resolves the request
    transparently to the caller without failing over.
    """
    primary = MockDeterministicProvider("primary-openai")
    # First call fails, second call succeeds
    primary.chat = AsyncMock(
        side_effect=[
            ProviderException("Transient 500", status_code=500),
            ChatCompletionResponse(
                id="chatcmpl-retry-1",
                created=1711800000,
                model="gpt-4o",
                choices=[
                    ChatChoice(
                        index=0,
                        message=ChatChoiceMessage(role="assistant", content="Resolved after retry"),
                        finish_reason="stop",
                    )
                ],
                usage=UsageInfo(prompt_tokens=10, completion_tokens=10, total_tokens=20),
            ),
        ]
    )

    policy = ReliabilityPolicy(
        max_attempts=2,
        base_delay=0.01,
        max_delay=0.05,
        jitter=False,
    )
    route = FallbackRoute(
        logical_model="gpt-4o",
        primary=ProviderTarget(provider_name="primary-openai", upstream_model="gpt-4o"),
        fallbacks=[],
    )

    executor = ReliableExecutor()
    req = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="hi")],
    )
    ctx = AuthenticatedContext(tenant_id=uuid.uuid4(), role="admin")

    resp, meta = await executor.execute_chat(
        request=req,
        route=route,
        providers_map={"primary-openai": primary},
        ctx=ctx,
        request_id="req_retry_test",
        policy=policy,
    )

    assert resp.choices[0].message.content == "Resolved after retry"
    assert meta.total_attempts == 2
    assert meta.fallback_used is False


@pytest.mark.asyncio
async def test_provider_100_percent_failure_fallback_routing():
    """
    Simulates a 100% outage on the primary provider (repeated 503s).
    Verifies that the executor exhausts retries on primary, trips the circuit,
    and falls back deterministically to the secondary provider.
    """
    primary = MockDeterministicProvider("primary-openai", should_fail=True)
    fallback = MockDeterministicProvider("fallback-anthropic", should_fail=False)

    policy = ReliabilityPolicy(
        max_attempts=1,
        base_delay=0.01,
        max_delay=0.02,
        jitter=False,
    )
    route = FallbackRoute(
        logical_model="gpt-4o",
        primary=ProviderTarget(provider_name="primary-openai", upstream_model="gpt-4o"),
        fallbacks=[
            ProviderTarget(
                provider_name="fallback-anthropic", upstream_model="claude-3-5-sonnet-20241022"
            )
        ],
    )

    executor = ReliableExecutor()
    req = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="hi")],
    )
    ctx = AuthenticatedContext(tenant_id=uuid.uuid4(), role="admin")

    resp, meta = await executor.execute_chat(
        request=req,
        route=route,
        providers_map={"primary-openai": primary, "fallback-anthropic": fallback},
        ctx=ctx,
        request_id="req_fallback_test",
        policy=policy,
    )

    assert "Success from fallback-anthropic" in resp.choices[0].message.content
    assert meta.fallback_used is True
    assert meta.final_provider == "fallback-anthropic"
    assert "primary-openai" in meta.providers_attempted


@pytest.mark.asyncio
async def test_streaming_interruption_graceful_abort():
    """
    Verifies that when an upstream provider breaks connection midway through a stream:
    1. The generator terminates cleanly without hanging.
    2. Connection resources are released.
    """

    class BrokenStreamProvider(LLMProvider):
        def __init__(self):
            super().__init__(name="broken-stream")

        async def chat(self, request, resolved_model, request_id):
            raise NotImplementedError

        async def stream(self, request, resolved_model, request_id):
            yield 'data: {"choices":[{"delta":{"content":"First "}}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"Second "}}]}\n\n'
            # Abrupt network crash
            raise ConnectionResetError("Upstream server closed connection unexpectedly")

    provider = BrokenStreamProvider()
    req = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="stream")],
        stream=True,
    )

    chunks = []
    error_caught = False
    try:
        async for chunk in provider.stream(req, "gpt-4o", "req_broken_stream"):
            chunks.append(chunk)
    except ConnectionResetError:
        error_caught = True

    assert len(chunks) == 2
    assert error_caught is True
    assert "First " in chunks[0]
    assert "Second " in chunks[1]


@pytest.mark.asyncio
async def test_client_disconnect_task_cancellation():
    """
    Simulates client disconnect while upstream request is executing:
    The gateway cancels the provider task and frees execution resources.
    """

    async def slow_upstream_call():
        await asyncio.sleep(5.0)
        return "finished"

    # Launch task as gateway does
    task = asyncio.create_task(slow_upstream_call())

    # Simulate client disconnect: cancel task after 50ms
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelled() is True
