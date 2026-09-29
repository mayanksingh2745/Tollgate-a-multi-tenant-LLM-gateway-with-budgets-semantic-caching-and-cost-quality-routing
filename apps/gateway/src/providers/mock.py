import asyncio
import time
from typing import AsyncIterator

from gateway.src.providers.base import (
    LLMProvider,
    ProviderAuthenticationError,
    ProviderException,
    ProviderTimeoutError,
)
from gateway.src.schemas.chat import (
    ChatChoice,
    ChatChoiceMessage,
    ChatChunkChoice,
    ChatChunkDelta,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    UsageInfo,
)


class MockProvider(LLMProvider):
    """
    Deterministic mock provider for unit tests, integration tests, and benchmarks.
    """

    def __init__(
        self,
        name: str = "mock_provider",
        latency_seconds: float = 0.0,
        should_fail: bool = False,
        failure_status: int = 502,
        failure_message: str = "Mock provider intentional failure",
        should_timeout: bool = False,
        response_text: str = "Hello from mock provider!",
    ):
        super().__init__(name=name, base_url="mock://localhost", api_key="mock_key")
        self.latency_seconds = latency_seconds
        self.should_fail = should_fail
        self.failure_status = failure_status
        self.failure_message = failure_message
        self.should_timeout = should_timeout
        self.response_text = response_text

    async def _simulate_delays_and_errors(self):
        if self.should_timeout:
            await asyncio.sleep(0.2)
            raise ProviderTimeoutError("Mock provider timed out")

        if self.latency_seconds > 0:
            await asyncio.sleep(self.latency_seconds)

        if self.should_fail:
            if self.failure_status == 401:
                raise ProviderAuthenticationError(self.failure_message)
            raise ProviderException(self.failure_message, status_code=self.failure_status)

    async def chat(
        self,
        request: ChatCompletionRequest,
        resolved_model: str,
        request_id: str,
    ) -> ChatCompletionResponse:
        await self._simulate_delays_and_errors()

        prompt_tokens = sum(len(m.content or "") for m in request.messages) // 4 + 5
        completion_tokens = len(self.response_text) // 4 + 2

        return ChatCompletionResponse(
            id=f"chatcmpl-{request_id}",
            object="chat.completion",
            created=int(time.time()),
            model=resolved_model,
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatChoiceMessage(role="assistant", content=self.response_text),
                    finish_reason="stop",
                )
            ],
            usage=UsageInfo(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    async def stream(
        self,
        request: ChatCompletionRequest,
        resolved_model: str,
        request_id: str,
    ) -> AsyncIterator[ChatCompletionChunk]:
        await self._simulate_delays_and_errors()

        words = self.response_text.split(" ")
        for i, word in enumerate(words):
            # First chunk emits role
            delta_content = word + (" " if i < len(words) - 1 else "")
            delta = ChatChunkDelta(role="assistant" if i == 0 else None, content=delta_content)
            chunk = ChatCompletionChunk(
                id=f"chatcmpl-{request_id}",
                object="chat.completion.chunk",
                created=int(time.time()),
                model=resolved_model,
                choices=[ChatChunkChoice(index=0, delta=delta, finish_reason=None)],
            )
            yield chunk
            if self.latency_seconds > 0:
                await asyncio.sleep(self.latency_seconds / len(words))

        # Final chunk with finish_reason="stop"
        yield ChatCompletionChunk(
            id=f"chatcmpl-{request_id}",
            object="chat.completion.chunk",
            created=int(time.time()),
            model=resolved_model,
            choices=[ChatChunkChoice(index=0, delta=ChatChunkDelta(), finish_reason="stop")],
        )
