import asyncio
import time
from typing import AsyncIterator, Optional

from gateway.src.providers.base import (
    LLMProvider,
    ProviderAuthenticationError,
    ProviderException,
    ProviderRateLimitError,
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
    Deterministic fault-injection mock provider for unit tests,
    integration tests, reliability suites, and benchmarks.
    """

    def __init__(
        self,
        name: str = "mock_provider",
        latency_seconds: float = 0.0,
        should_fail: bool = False,
        failure_status: int = 502,
        failure_message: str = "Mock provider failure",
        should_timeout: bool = False,
        response_text: str = "Hello from mock provider!",
        retry_after: Optional[float] = None,
        failures_until_success: Optional[int] = None,
        failure_mode: str = "none",  # "timeout", "connection_error", "429", "500", "502", "503", "400", "401", "stream_before", "stream_after"
    ):
        super().__init__(name=name, base_url="mock://localhost", api_key="mock_key")
        self.latency_seconds = latency_seconds
        self.should_fail = should_fail
        self.failure_status = failure_status
        self.failure_message = failure_message
        self.should_timeout = should_timeout
        self.response_text = response_text
        self.retry_after = retry_after
        self.failures_until_success = failures_until_success
        self.failure_mode = failure_mode
        self.call_count: int = 0

    def _determine_error(self) -> Optional[Exception]:
        # Handle failures_until_success
        if self.failures_until_success is not None:
            if self.call_count <= self.failures_until_success:
                return self._create_failure()
            return None

        if self.should_timeout or self.failure_mode == "timeout":
            return ProviderTimeoutError("Mock provider call timed out")

        if self.failure_mode == "connection_error":
            return ProviderException("Connection reset by peer", status_code=503)

        if self.failure_mode == "429" or self.failure_status == 429:
            err = ProviderRateLimitError(self.failure_message)
            err.retry_after = self.retry_after
            return err

        if self.failure_mode == "400" or self.failure_status == 400:
            return ProviderException(self.failure_message, status_code=400)

        if self.failure_mode == "401" or self.failure_status == 401:
            return ProviderAuthenticationError(self.failure_message)

        if self.failure_mode in ("500", "502", "503"):
            return ProviderException(self.failure_message, status_code=int(self.failure_mode))

        if self.should_fail:
            return self._create_failure()

        return None

    def _create_failure(self) -> Exception:
        if self.failure_status == 401:
            return ProviderAuthenticationError(self.failure_message)
        elif self.failure_status == 429:
            err = ProviderRateLimitError(self.failure_message)
            err.retry_after = self.retry_after
            return err
        return ProviderException(self.failure_message, status_code=self.failure_status)

    async def chat(
        self,
        request: ChatCompletionRequest,
        resolved_model: str,
        request_id: str,
    ) -> ChatCompletionResponse:
        self.call_count += 1

        if self.latency_seconds > 0:
            await asyncio.sleep(self.latency_seconds)

        err = self._determine_error()
        if err is not None:
            raise err

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
        self.call_count += 1

        if self.latency_seconds > 0:
            await asyncio.sleep(self.latency_seconds)

        # Check for failure before first chunk
        if self.failure_mode == "stream_before":
            raise ProviderException("Stream failed before first chunk", status_code=503)

        err = self._determine_error()
        if err is not None and self.failure_mode != "stream_after":
            raise err

        words = self.response_text.split(" ")
        for i, word in enumerate(words):
            # Check for failure after emitting chunks
            if self.failure_mode == "stream_after" and i == 2:
                raise ProviderException(
                    "Stream connection dropped mid-transmission", status_code=503
                )

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

        # Final chunk
        yield ChatCompletionChunk(
            id=f"chatcmpl-{request_id}",
            object="chat.completion.chunk",
            created=int(time.time()),
            model=resolved_model,
            choices=[ChatChunkChoice(index=0, delta=ChatChunkDelta(), finish_reason="stop")],
        )
